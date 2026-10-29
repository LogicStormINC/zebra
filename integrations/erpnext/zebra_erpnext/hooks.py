app_name = "zebra_erpnext"
app_title = "Zebra ERPNext"
app_publisher = "zebra"
app_description = "Zebra Cloud Agent for ERPNext"
app_email = "admin@example.invalid"
app_license = "GPL-3.0-only"
required_apps = ["erpnext"]
app_include_js = ["/assets/zebra_erpnext/zebra.js?v=20261029-workbench-b12"]
app_include_css = ["/assets/zebra_erpnext/zebra.css?v=20261029-workbench-b12"]
after_install = "zebra_erpnext.install.setup"
after_migrate = "zebra_erpnext.install.setup"

scheduler_events = {"hourly": ["zebra_erpnext.install.prune_grants"]}
