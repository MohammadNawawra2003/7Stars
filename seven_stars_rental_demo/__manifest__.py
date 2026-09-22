{
    'name': "Seven Stars Halls — Demo Data",
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': "Realistic demo data for the Seven Stars booking workflow",
    'author': "Al Shayeb",
    'license': 'OEEL-1',
    'depends': ['seven_stars_rental'],
    # Data only. No Python, no business logic — every rule lives in seven_stars_rental
    # and these records merely obey it (spec §18).
    #
    # These files sit under 'data', not 'demo', for three runtime-verified reasons:
    #   1. load_data() forces noupdate=True on everything loaded from a 'demo' key
    #      (odoo/modules/loading.py:59), whatever the file itself says. Under 'demo' an
    #      edited record can never be re-applied by -u, which is a Phase 0 acceptance item.
    #   2. load_demo() catches any failure and downgrades it to a warning, reporting the
    #      module as installed with no data (odoo/modules/loading.py:64-87). A broken demo
    #      file would pass CI silently. Under 'data' it is a hard error.
    #   3. Odoo 19 does not load demo data unless --with-demo is passed; --without-demo is
    #      documented as the default (odoo/tools/config.py:233-236). Under 'data' this
    #      addon populates a database on Odoo.sh and locally without a special flag.
    #
    # This addon is the demonstration/starter dataset: install it when you want a populated
    # system, uninstall it to remove the records. It is not noupdate, so
    # `-u seven_stars_rental,seven_stars_rental_demo` re-applies an edited record.
    'data': [
        'data/demo_company.xml',
        'data/demo_users.xml',
        'data/demo_partners.xml',
        'data/demo_products.xml',
        'data/demo_pricelists.xml',
    ],
    'installable': True,
    'application': False,
}
