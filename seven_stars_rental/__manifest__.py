{
    'name': "Seven Stars Halls — Rental",
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': "Hall booking, contracts and payments for Seven Stars Halls",
    'author': "Al Shayeb",
    'license': 'OEEL-1',            # depends on Enterprise sale_renting
    'depends': ['sale_renting'],    # brings sale, web_gantt, account*, product, portal, analytic
    'data': [
        'security/res_groups.xml',
        'security/ir.model.access.csv',
        'security/ir_rules.xml',
        'data/ss_base_data.xml',
        'data/ss_pricelist_data.xml',
        'wizard/ss_payment_register_views.xml',   # the booking form links to it
        'views/sale_order_views.xml',
        'views/product_template_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'report/report_contract_templates.xml',
        'report/report_operational_templates.xml',
        'report/report_payment_templates.xml',
        'report/report_actions.xml',
        'views/seven_stars_menus.xml',        # menus last, per Odoo convention
    ],
    'assets': {
        'web.report_assets_common': [
            'seven_stars_rental/static/src/scss/report_font.scss',
        ],
    },
    'installable': True,
    'application': True,            # one app carrying the whole booking workflow
}
