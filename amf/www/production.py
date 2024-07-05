import json
import frappe
from frappe import _
from frappe.utils.data import now_datetime
from frappe.utils.file_manager import save_file
from weasyprint import HTML

@frappe.whitelist()  # Allows this method to be called from the client side
def create_work_order(form_data: str) -> dict:
    try:
        # Parse form data from JSON string
        data = json.loads(form_data)
        # Validate item existence
        if not frappe.db.exists('Item', data['item_code']):
            return {'success': False, 'message': 'Item code not found'}
        
        # Fetch the BOM number based on the raw material and ensure it's an active BOM
        bom_no_list = frappe.db.get_all('BOM Item', 
                                     {'item_code': data['raw_material'], 'parenttype': 'BOM', 'parentfield': 'items'}, 
                                     ['parent'])
        print(bom_no_list)
        if not bom_no_list :
                    return {'success': False, 'message': f"No BOM found for raw material {data['raw_material']}"}
        
        matched_bom_no = None
        
        for bom in bom_no_list:
            bom_no = bom['parent']
            bom_item_code = frappe.db.get_value('BOM', {'name': bom_no, 'is_active': 1}, 'item')
            if bom_item_code == data['item_code']:
                matched_bom_no = bom_no
                break

        print(matched_bom_no)

        # Create and submit the work order document
        work_order = frappe.get_doc({
            'doctype': 'Work Order',
            'production_item': data['item_code'],
            'bom_no': matched_bom_no,
            'destination': 'N/A',
            'qty': int(data['quantity']) + int(data['scrap_quantity']),
            'wip_warehouse': 'Main Stock - AMF21',
            'fg_warehouse': 'Quality Control - AMF21',
            'company': frappe.db.get_single_value('Global Defaults', 'default_company'),
            'assembly_specialist_start': data['machinist'],
            'assembly_specialist_end': data['machinist'],
            'start_date_time': data['start_date'],
            'end_date_time': data['end_date'],
            'scrap_qty': data['scrap_quantity'],
            'machine': data['machine'],
            'skip_transfer': 1,
            'raw_material': data['raw_material'],
            'raw_material_batch': data['raw_material_batch'],
            'raw_material_dim': data['raw_material_dimensions'],
            'start_datetime': data['start_date'],
            'end_datetime': data['end_date'],
            'cycle_time': data['cycle_time'],
            'program': data['program'],
            'program_time': data['programmation'],
            'setup_time': data['met'],
            'production_comments': data['comment'],
            'simple_description': data['commentprd'],
            'label': data['m_number'],
            # Additional fields can be added here if required
        })
        work_order.insert()
        work_order.submit()
        #frappe.db.commit()
        # Assuming make_stock_entry_ returns Document objects or similar, not just names/IDs
        manufacture_entry, manufacture_batch = make_stock_entry_(work_order.name, 'Manufacture', int(data['quantity']), int(data['scrap_quantity']))
        
        # Additional stock entry for scrap if necessary
        transfer_entry = None
        if int(data['scrap_quantity']) > 0:
            transfer_entry = make_stock_entry_(work_order.name, 'Material Transfer', None, int(data['scrap_quantity']), manufacture_entry)

        # Commit only after all operations succeed
        frappe.db.commit()

        # Prepare and return response
        return {
            'success': True,
            'work_order_id': work_order.name,
            'stock_entry_id': manufacture_entry.name if manufacture_entry else None,
            'transfer_entry_id': transfer_entry.name if transfer_entry else None,
            'batch': manufacture_batch if manufacture_batch else None
        }

    except Exception as e:
        # Log and return the error
        frappe.log_error(frappe.get_traceback(), 'Work Order Creation Failed')
        return {'success': False, 'message': str(e)}
    
@frappe.whitelist()
def get_item_name(item_code):
    item_name = frappe.db.get_value('Item', {'item_code': item_code}, 'item_name')
    if item_name:
        return {'item_name': item_name}
    else:
        item_name = frappe.db.get_value('Item', {'reference_code': item_code}, 'item_name')
        if item_name:
            return {'item_name': item_name}
        else:
            return {'item_name': 'Item not found'}

@frappe.whitelist()
def get_mat_items_from_bom(item_code):
    # Get all active BOMs for the given item code
    active_boms = frappe.db.get_list('BOM', {'item': item_code, 'is_active': 1}, 'name')
    
    if not active_boms:
        return {'message': _('No active BOM found for item code {0}').format(item_code), 'items': []}
    
    mat_items = []
    
    # Iterate over each BOM to get the BOM items
    for bom in active_boms:
        bom_items = frappe.db.get_list('BOM Item',
                                       filters={
                                           'parent': bom['name'],
                                           'item_code': ['like', 'MAT%']
                                       },
                                       fields=['item_code', 'item_name'])
        mat_items.extend(bom_items)
    
    if mat_items:
        # Create a list to hold "item_code: item_name" strings
        items_list = ['{}: {}'.format(item['item_code'], item['item_name']) for item in mat_items]
        return {
            'message': 'MAT items found',
            'items': items_list
        }
    else:
        return {
            'message': 'No "MAT" items found in the active BOMs for item code {}'.format(item_code),
            'items': []
        }

@frappe.whitelist()
def make_stock_entry_(work_order_id, purpose, qty=None, scrap=None, ft_stock_entry=None):
    work_order = frappe.get_doc("Work Order", work_order_id)
    # Create the first stock entry for production or scrap
    if (purpose == 'Manufacture'):
        stock_entry, batch_no = create_stock_entry(work_order, purpose, qty, scrap, True if qty else False)
    
    # Commit after the first stock entry to ensure data integrity
    #frappe.db.commit()

    # Create the second stock entry for transferring finished goods to scrap, if scrap is provided
    if qty is None:
        create_stock_entry(work_order, purpose, None, scrap, False, ft_stock_entry)
        # Commit after creating the second stock entry
        #frappe.db.commit()

    # Return the first stock entry's details (and batch_no if applicable)
    if qty:
        return stock_entry.as_dict(), batch_no
        
def create_stock_entry(work_order, purpose, qty, scrap, from_bom, ft_stock_entry=None):
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.purpose = purpose
    stock_entry.work_order = work_order.name
    stock_entry.company = work_order.company
    stock_entry.from_bom = from_bom
    stock_entry.bom_no = work_order.bom_no if from_bom else None
    stock_entry.use_multi_level_bom = work_order.use_multi_level_bom
    
    if purpose == "Material Transfer":
        stock_entry.fg_completed_qty = scrap  # For material transfer, we only consider scrap quantity
        stock_entry.from_warehouse = 'Quality Control - AMF21'
        stock_entry.to_warehouse = 'Scrap - AMF21'
        item = ft_stock_entry['items'][-1]
        item['qty'] = scrap
        item['s_warehouse'] = stock_entry.from_warehouse
        item['t_warehouse'] = stock_entry.to_warehouse
        stock_entry.append('items', item)
        
    else:  # For Manufacture or other purposes
        stock_entry.fg_completed_qty = qty + scrap
        stock_entry.from_warehouse = 'Main Stock - AMF21' if qty else 'Quality Control - AMF21'
        stock_entry.to_warehouse = 'Quality Control - AMF21' if qty else 'Scrap - AMF21'
        if from_bom:
            stock_entry.get_items()

    stock_entry.set_stock_entry_type()
    stock_entry.get_stock_and_rate()

    stock_entry.insert()
    batch_no = create_batch_if_manufacture(stock_entry) if qty else None
    
    stock_entry.submit()
    return stock_entry, batch_no

@frappe.whitelist()
def create_batch_if_manufacture(self):
    if self.purpose == 'Manufacture' and self.items:
        last_item = self.items[-1]
        item_has_batch_no = frappe.db.get_value('Item', last_item.item_code, 'has_batch_no')

        if item_has_batch_no:
            posting_date = self.posting_date
            batch_id = f"{last_item.item_code} {posting_date} AMF {self.fg_completed_qty}"
            existing_batch = frappe.db.exists('Batch', {'batch_id': batch_id})

            if existing_batch:
                # Handling duplicate - generating a unique batch ID
                # Example: appending a timestamp or a counter
                unique_suffix = now_datetime().strftime('%H%M%S')  # Using timestamp for uniqueness
                batch_id += f" {unique_suffix}"

            # Create new batch with either the original or updated unique batch ID
            new_batch_doc = frappe.get_doc({
                'doctype': 'Batch',
                'item': last_item.item_code,
                'batch_id': batch_id,
                'work_order': self.work_order,
            })
            new_batch_doc.insert()
            last_item.batch_no = new_batch_doc.name
            return last_item.batch_no
        
@frappe.whitelist()
def attach_sticker_image(work_order_id, image_data):
    try:
        # Ensure work_order_id is valid
        if not frappe.db.exists('Work Order', work_order_id):
            return {'success': False, 'message': 'Work Order not found'}

        # Decode the Base64 image data
        from base64 import b64decode
        image_content = b64decode(image_data.split(",")[1])

        # Save the image and attach it to the Work Order
        file_name = f"{work_order_id}_sticker.png"
        filedoc = save_file(file_name, image_content, 'Work Order', work_order_id, is_private=1)

        # Optionally update a custom field (e.g., 'sticker_image') with the file URL
        frappe.db.set_value('Work Order', work_order_id, 'sticker_image', filedoc.file_url)
        return {'success': True}
    except Exception as e:
        frappe.log_error(message=str(e), title="Attach Sticker Image Error")
        return {'success': False, 'message': str(e)}

@frappe.whitelist()
def html_to_pdf(html_content):
    # Convert HTML to PDF
    pdf = HTML(string=html_content).write_pdf()

    # Save the PDF to a file or return it as a response
    file_name = "output.pdf"
    with open(file_name, "wb") as f:
        f.write(pdf)

    return file_name

@frappe.whitelist()
def html_to_pdf_and_attach(work_order_id, html_content):
    try:
        # Ensure work_order_id is valid
        if not frappe.db.exists('Work Order', work_order_id):
            return {'success': False, 'message': 'Work Order not found'}

        # Convert HTML to PDF
        pdf_content = HTML(string=html_content).write_pdf()
        
        # Convert the PDF content to bytes if it's not already in bytes format
        if not isinstance(pdf_content, bytes):
            pdf_content = pdf_content.encode()

        # Save the PDF and attach it to the Work Order
        file_name = f"{work_order_id}_sticker.pdf"
        filedoc = save_file(file_name, pdf_content, 'Work Order', work_order_id, is_private=1)

        # Optionally update a custom field (e.g., 'sticker_image') with the file URL
        frappe.db.set_value('Work Order', work_order_id, 'sticker_image', filedoc.file_url)

        return {'success': True, 'message': 'PDF successfully attached', 'file_url': filedoc.file_url}
    except Exception as e:
        frappe.log_error(message=str(e), title="Attach PDF Error")
        return {'success': False, 'message': str(e)}

def test_bom():
    raw = 'MAT.1004'
    bom_no = frappe.db.get_value('BOM Item', {'item_code': raw}, 'parent')
    if not bom_no:
        print("Error BOM")
    else:
        print(bom_no)