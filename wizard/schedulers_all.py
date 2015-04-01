# -*- coding: utf-8 -*-
import logging
import threading
import time

from openerp.osv import osv, fields
from datetime import datetime

_logger = logging.getLogger(__name__)

class revel_sync_data(osv.osv_memory):
    _name = 'revelpos.sync'
    _description = 'Syncronize order data from Revel POS and Google Calendar schedulers'

    _columns = {
        'date': fields.date('Date', required=True)
    }
        
    def get_data_from_apis(self, cr, uid, ids, context=None):
        data = self.read(cr, uid, ids, context=context)[0]
        date = datetime.strptime(data['date'], "%Y-%m-%d").date()
        #threaded_calculation = threading.Thread(target=self.pool.get('api.credential').synchronize_orders_cron, args=(cr, uid, date, context))
        #threaded_calculation.start()
        self.pool.get('api.credential').action_get_data_from_apis(cr, uid, date, context)
        return {'type': 'ir.actions.act_window_close'}


# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
