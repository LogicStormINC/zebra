FROM frappe/erpnext:v16.52.1
USER root
COPY --chown=frappe:frappe . /home/frappe/frappe-bench/apps/zebra_erpnext
# ponytail: this plugin adds no Python dependencies; use a wheel if that changes.
RUN /home/frappe/frappe-bench/env/bin/python -c "import site,pathlib; pathlib.Path(site.getsitepackages()[0], 'zebra_erpnext.pth').write_text('/home/frappe/frappe-bench/apps/zebra_erpnext\\n')"
RUN ln -s /home/frappe/frappe-bench/apps/zebra_erpnext/zebra_erpnext/public /home/frappe/frappe-bench/assets/zebra_erpnext
USER frappe
