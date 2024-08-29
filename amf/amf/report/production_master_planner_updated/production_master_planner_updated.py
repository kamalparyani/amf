# import the necessary libraries
from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import add_months, add_years, today
from datetime import timedelta

def execute(filters=None):
    if not filters:
        filters = {}

    # Set default values for date filters
    filters.setdefault("from_date", add_years(today(), -2))
    filters.setdefault("to_date", add_years(today(), 2))

    # define the columns for the report
    columns = get_columns()

    # fetch the data from the database
    data = get_data(filters)

    # return the columns and data to display the report
    return columns, data

def get_columns():
    return [
        _("ITEM CODE: ITEM NAME")+":Link/Item:350",
        _("SO")+":Link/Sales Order:100",
        _("TYPE")+":Link/Sales Order:100",
        _("QTY")+":Int:50",
        _("%") + ":Percent:50",
        _("CUSTOMER")+":Link/Customer:250",
        _("TOTAL")+":Currency/Sales Order:125",
        _("SHIP. DATE")+":Date:100",
        _("START DATE") + ":Date:100",
        _("W#")+":Int:25",
        _("WO")+":Link/Work Order:100",
        _("END DATE")+":Date:100",
        _("DN")+":Link/Delivery Note:100",
        _("DN STATUS")+":Link/Delivery Note:100",
        
    ]

def get_data(filters):
    hide_completed_filter = "AND ((so_item.delivered_qty / so_item.qty) * 100) < 100" if filters.get("hide_completed") else ""
    hide_rnd = "AND LOWER(TRIM(so.sales_order_type)) != 'r&d'" if filters.get("no_rnd") else ""
    
    # SQL query to fetch the required data
    sql_query = """
        SELECT
            CONCAT(so_item.item_code, ': ', item.item_name) as item_code_and_name,
            so.name as sales_order,
            so.sales_order_type as type,
            so_item.qty,
            ROUND((so_item.delivered_qty / so_item.qty) * 100) as progress,
            so.customer,
            so.grand_total,
            so_item.delivery_date as estimated_shipping_date,
            DATE_SUB(so_item.delivery_date, INTERVAL (item.timetoproduce * so_item.qty) DAY) as start_date,
            WEEK(so_item.delivery_date) as week_number,
            wo.name as work_order,
            wo.p_e_d as work_order_planned_end_date,
            dni.parent,
            dn.status,
            item.timetoproduce
        FROM
            `tabSales Order` so
        JOIN
            `tabSales Order Item` so_item ON so.name = so_item.parent
        LEFT JOIN
            `tabWork Order` wo ON wo.sales_order = so.name AND wo.production_item = so_item.item_code
        JOIN
            `tabItem` item ON so_item.item_code = item.name
        LEFT JOIN
            `tabDelivery Note Item` dni ON so_item.name = dni.so_detail
        LEFT JOIN
            `tabDelivery Note` dn ON dni.parent = dn.name AND dn.status != 'Cancelled'
        WHERE
            so.docstatus = 1
            AND so.status != 'Closed'
            AND so_item.delivery_date BETWEEN '{0}' AND '{1}'
            {2}  -- Add the hide_completed_filter here
            {3}  -- Add the hide_rnd here
        GROUP BY
            so_item.name
        ORDER BY
            so_item.delivery_date ASC, so.customer ASC
    """.format(filters.get("from_date"), filters.get("to_date"), hide_completed_filter, hide_rnd)

    # execute the query and fetch the result
    data = frappe.db.sql(sql_query, as_list=True)

    # Calculate START DATE based on time_to_produce and quantity
    # for row in data:
    #     estimated_shipping_date = row[4]
    #     time_to_produce = row[8]
    #     quantity = row[2]
    #     start_date = estimated_shipping_date - timedelta(days=(time_to_produce * quantity))
    #     row.append(start_date)

    # apply the color scheme to the week number column
    # for row in data:
    #     week_number = row[5]
    #     print("Week Number:", week_number)  # Print the week_number variable
    #     if week_number < 10:
    #         row[5] = "<span style='color: green;'>{}</span>".format(week_number)
    #     elif week_number < 20:
    #         row[5] = "<span style='color: orange;'>{}</span>".format(week_number)
    #     else:
    #         row[5] = "<span style='color: red;'>{}</span>".format(week_number)

    return data
