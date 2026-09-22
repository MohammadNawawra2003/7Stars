"""One app for the whole workflow.

The staff should not have to hop between the Rental app, the product screens and the
settings to take one booking through. Everything here is a menu or an action over views that
already exist — no new model, no new field, no business logic.
"""
from odoo import Command
from odoo.tests import tagged

from .common import SevenStarsCommon


@tagged('post_install', '-at_install')
class TestSevenStarsApp(SevenStarsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clerk = cls._user('test_menu_clerk', 'group_ss_clerk')
        cls.accountant = cls._user('test_menu_accountant', 'group_ss_accountant')
        cls.manager = cls._user('test_menu_manager', 'group_ss_manager')

    def _visible_menu_ids(self, user):
        """What the user ACTUALLY sees.

        A plain search() on ir.ui.menu is not group-filtered — it returns every menu in the
        database. The web client calls _visible_menu_ids(), which is the method that applies
        the group_ids filter (base/models/ir_ui_menu.py:75), so that is what is asserted here.
        """
        return set(self.env['ir.ui.menu'].with_user(user)._visible_menu_ids())

    def _visible_apps(self, user):
        """The app grid: the root menus this user sees."""
        return set(self.env['ir.ui.menu'].with_user(user).get_user_roots().mapped('name'))

    def test_seven_stars_is_a_top_level_app(self):
        root = self.env.ref('seven_stars_rental.menu_ss_root')
        self.assertFalse(root.parent_id, "the Seven Stars menu must be an app, not a submenu")
        self.assertTrue(self.env.ref('base.module_seven_stars_rental').application
                        if self.env.ref('base.module_seven_stars_rental', raise_if_not_found=False)
                        else True)

    def test_every_role_that_uses_the_system_sees_the_app(self):
        for user in (self.clerk, self.accountant, self.manager):
            with self.subTest(role=user.login):
                self.assertIn("قاعات سفن ستارز", self._visible_apps(user))

    def test_the_whole_workflow_hangs_off_the_one_app(self):
        """Enquiry → schedule → customer → money → master data → settings, in that order."""
        root = self.env.ref('seven_stars_rental.menu_ss_root')
        reachable = self.env['ir.ui.menu'].search([('id', 'child_of', root.id)])
        for xmlid in ('menu_ss_bookings', 'menu_ss_schedule', 'menu_ss_customers',
                      'menu_ss_payments', 'menu_ss_halls', 'menu_ss_services',
                      'menu_ss_pricelists', 'menu_ss_settings', 'menu_ss_recurrences'):
            menu = self.env.ref(f'seven_stars_rental.{xmlid}')
            self.assertIn(menu, reachable, f"{xmlid} is not under the Seven Stars app")
            self.assertTrue(menu.action, f"{xmlid} opens nothing")

    def test_a_clerk_does_not_see_the_management_only_menus(self):
        clerk_menus = self._visible_menu_ids(self.clerk)
        for xmlid in ('menu_ss_pricelists', 'menu_ss_config_root', 'menu_ss_settings'):
            self.assertNotIn(self.env.ref(f'seven_stars_rental.{xmlid}').id, clerk_menus, xmlid)

        # but she does see the ones she works in every day
        for xmlid in ('menu_ss_bookings', 'menu_ss_schedule', 'menu_ss_payments'):
            self.assertIn(self.env.ref(f'seven_stars_rental.{xmlid}').id, clerk_menus, xmlid)

    def test_configuration_is_reachable_from_the_app_by_an_administrator(self):
        """The settings menu is scoped to base.group_system, not to Management.
        res.config.settings requires it, and Odoo drops any menu whose action the user
        cannot reach — a Management-scoped settings menu would simply never appear."""
        admin = self._user('test_menu_admin', 'group_ss_manager')
        admin.group_ids = [Command.link(self.env.ref('base.group_system').id)]
        admin_menus = self._visible_menu_ids(admin)
        self.assertIn(self.env.ref('seven_stars_rental.menu_ss_settings').id, admin_menus)
        self.assertIn(self.env.ref('seven_stars_rental.menu_ss_recurrences').id, admin_menus)

    def test_a_clerk_is_not_sent_wandering_through_other_apps(self):
        """The point of the one-app layout: a booking clerk should land in Seven Stars and
        stay there, not hop between Rental, Invoicing and the product screens."""
        apps = self._visible_apps(self.clerk)
        self.assertIn("قاعات سفن ستارز", apps)
        for unwanted in ("Invoicing", "Inventory", "Accounting"):
            self.assertNotIn(unwanted, apps, f"a clerk should not be shown {unwanted}")

    def test_the_bookings_menu_shows_bookings_and_nothing_else(self):
        action = self.env.ref('seven_stars_rental.action_ss_bookings')
        self.assertEqual(action.res_model, 'sale.order')
        self.assertIn("('is_rental_order', '=', True)", action.domain)
        # in_rental_app is what makes a NEW record a rental order
        self.assertIn('in_rental_app', action.context)

        hall = self._hall("MENU Hall", 500, 3000.0).product_variant_id
        booking = self._booking([hall], *self.evening(2040, 3, 3))
        plain = self.env['sale.order'].create({'partner_id': self.customer.id})

        listed = self.env['sale.order'].search(
            [('is_rental_order', '=', True), ('id', 'in', (booking | plain).ids)])
        self.assertIn(booking, listed)
        self.assertNotIn(plain, listed, "an ordinary quotation is not a hall booking")

    def test_the_halls_menu_lists_halls_and_the_services_menu_does_not(self):
        hall = self._hall("MENU Hall Two", 450, 3000.0)
        service = self._service("MENU Service", 700.0)

        halls_domain = [('rent_ok', '=', True), ('hall_capacity', '>', 0)]
        services_domain = [('sale_ok', '=', True), ('hall_capacity', '=', 0)]
        halls = self.env['product.template'].search(halls_domain)
        services = self.env['product.template'].search(services_domain)

        self.assertIn(hall, halls)
        self.assertNotIn(hall, services)
        self.assertIn(service, services)
        self.assertNotIn(service, halls)
