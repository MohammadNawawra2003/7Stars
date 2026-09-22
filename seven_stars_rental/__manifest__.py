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
        'data/ss_base_data.xml',
    ],
    'installable': True,
    'application': False,           # extends the Rental app, it is not a new app
}
