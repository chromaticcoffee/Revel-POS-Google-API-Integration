# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
#
#    Copyright (C) 2014 Novobi LLC (<http://novobi.com>)
#
##############################################################################
import sys, os
from openerp.osv import fields, osv, orm

from datetime import datetime, timedelta

import openerp
from openerp import tools
from openerp import SUPERUSER_ID
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, exception_to_unicode

from openerp.tools.translate import _
from openerp.http import request

from dateutil import parser
import pytz
from pytz import timezone
from openerp.osv import fields, osv

import logging
_logger = logging.getLogger(__name__)

class api_credential(osv.osv):
    _name = 'api.credential'
    _inherit = ['mail.thread']
    _columns = {
        'name'                  : fields.char('Name'),
        'config_id'             : fields.many2one('pos.config', string="POS", required=True, copy=False),
        # Google Calendar Credential Holders
        'google_calendar_id'                : fields.char('Calendar Id'),
        'google_calendar_client_id'         : fields.char('Client Id'),
        'google_calendar_client_secret'     : fields.char('Client Secret'),
        'google_calendar_redirect_uri'      : fields.char('Redirect URI'),
        'google_calendar_rtoken'            : fields.char('Refresh Token'),
        'google_calendar_token'             : fields.char('User token'),
        'google_calendar_token_validity'    : fields.datetime('Token Validity'),
        'google_calendar_cal_id'            : fields.char('Calendar ID', help='Last Calendar ID who has been synchronized. If it is changed, we remove \
all links between GoogleID and Odoo Google Internal ID'),
        # Revel POS Credential Holders
        'revelpos_client_id': fields.char('Client Id'),
        'revelpos_client_secret': fields.char('Client Secret'),   
        'establishment_id': fields.char('Establishment ID', required=True), 
        'active': fields.boolean('Active')
    }
    _defaults = {
        'active': 1,
    }
    
    def get_client_info(self, cr, uid, id=None, context=None):
        if id:
            for credential in self.browse(cr, uid, int(id), context=context):
                return credential
        return None
    
    def synchronize_orders_cron(self, cr, uid, sync_date=None, context=None):
        _logger.info("Revel POS Synchro - Started by cron")
        try:
            resp = self.action_get_data_from_apis(cr, uid, sync_date=sync_date, context=context)            
        except Exception, e:
            _logger.info("Revel POS Synchro - Exception : %s !" % exception_to_unicode(e))
        _logger.info("Revel POS Synchro - Ended by cron")
    
    def action_get_data_from_apis(self, cr, uid, sync_date=None, context=None):  
        if context is None:
            context = {}
            
        rc_obj = self.pool.get('api.credential')
        rm_obj = self.pool.get('revelpos.modifier')
        rp_obj = self.pool.get('revelpos.product')
        rt_obj = self.pool.get('revelpos.tax')
        ro_obj = self.pool.get('revelpos.order')
        rl_obj = self.pool.get('revelpos.order.line')
        pm_obj = self.pool.get('revelpos.payment')
        ti_obj = self.pool.get('revelpos.till')
        po_obj = self.pool.get('revelpos.payout')
        
        pos_session_obj = self.pool.get('pos.session')
        pos_order_obj = self.pool.get('pos.order')
        acc_bank_obj = self.pool.get('account.bank.statement')

        # Look for Revel POS credentials
        credential_ids = rc_obj.search(cr, uid, [], context=context)
        
        # If found
        if credential_ids:
            if sync_date:                                 
                start_date = sync_date
                end_date = start_date + timedelta(days=1)   
            else:
                end_date = datetime.now().date()                
                start_date = end_date - timedelta(days=1)
            # Iterate on credential list
            for credential_obj in rc_obj.browse(cr, uid, credential_ids, context=context): 
                if not credential_obj.active:
                    continue
                _logger.info("Revel POS Synchro - Starting synchronization for [%s] " % credential_obj.config_id.name)
                #try:
                    # create and open POS session
                context['config_id'] = credential_obj.config_id.id
                credential = {
                                'client_id' : credential_obj.revelpos_client_id, 
                                'client_secret' : credential_obj.revelpos_client_secret
                }        
                # Step 0: Get all till and create sessions
                ti_obj.set_credential(credential)
                filter = {
                    'establishment': credential_obj.establishment_id
                }
                till_field_list = ['id', 'opened', 'amount_till_set', 'amount_should_be', 'amount_present', 'created_date', 'closed']
                till_dict = ti_obj.get_data_dict(cr, uid, filter=filter, field_list=till_field_list, \
                                                       expanded_fields=[], start_date=start_date, end_date=end_date, context=context) 
                
                if not till_dict:
                    new_session = {
                        'user_id': 1,
                        'config_id': credential_obj.config_id.id,
                        'start_at': datetime.combine(start_date, datetime.min.time()),
                        'stop_at': datetime.combine(start_date, datetime.max.time()),
                    }
                    pos_session_id = pos_session_obj.create(cr, uid, new_session, context=context)
                    context['pos_session'] = [pos_session_id]
                else:
                    context['pos_session'] = [obj.get('id') for obj in till_dict.values()]
                
                # Step 1: Get all taxes
                #print 'Get account tax'
                #rt_obj.set_credential(credential)
                #tax_field_list = ['id', 'name', 'tax_rate', 'active']
                #tax_dict = rt_obj.get_data_dict(cr, uid, field_list=tax_field_list, expanded_fields=['tax_rate'], context=context)
                
                # Step 2a: Get all modifiers from API
                rm_obj.set_credential(credential)
                filter = {
                    'establishment': credential_obj.establishment_id
                }
                modifier_field_list = ['id', 'name', 'price', 'cost', 'active']
                product_dict = rm_obj.get_data_dict(cr, uid, filter=filter, field_list=modifier_field_list, context=context)
                
                # Step 2b: Get all products from API 
                #print 'Get product list'
                #rp_obj.set_credential(credential)
                #product_field_list = ['id', 'name', 'price', 'tax']
                #product_dict.update(rp_obj.get_data_dict(cr, uid, field_list=product_field_list, expanded_fields=['tax'], context=context))

                # Step 3: Get all order in day 
                ro_obj.set_credential(credential)
                
                filter = {
                    'created_date__gte': start_date.strftime("%Y-%m-%d"),
                    'created_date__lt' : end_date.strftime("%Y-%m-%d"),
                    'establishment': credential_obj.establishment_id
                }
                order_field_list = ['id', 'created_date', 'created_by', 'deleted', 'bill_parent', 'closed', 'is_unpaid']
                order_dict = {}
                order_dict = ro_obj.get_data_dict(cr, uid, filter=filter, field_list=order_field_list, expanded_fields=['created_by'], context=context)
                
                # Check updated orders
                filter = {
                    'updated_date__gte': start_date.strftime("%Y-%m-%d"),
                    'updated_date__lt' : end_date.strftime("%Y-%m-%d"),
                    'establishment': credential_obj.establishment_id
                }
                order_field_list = ['id', 'created_date', 'created_by', 'deleted', 'bill_parent', 'closed', 'is_unpaid']
                order_dict2 = ro_obj.get_data_dict(cr, uid, filter=filter, field_list=order_field_list, expanded_fields=['created_by'], context=context)
                
                order_dict.update(order_dict2)
                
                # Step 4: Get all order lines
                rl_obj.set_credential(credential)
                order_ids_str = ','.join(order_dict.keys())
                filter = {
                    'order__in': order_ids_str
                }
                orderline_field_list = ['id', 'product', 'price', 'quantity', 'order', 'applied_taxes', 'tax_included', 'void_ref_uuid', \
                                         'modifieritems', 'modifier_cost', 'modifier_amount', 'deleted']
                order_line_dict = rl_obj.get_data_dict(cr, uid, filter=filter, field_list=orderline_field_list, \
                                                       expanded_fields=['product', 'order', 'applied_taxes', 'modifieritems'], context=context)  
                
                # Step 4: Get all order lines
                pm_obj.set_credential(credential)
                filter = {
                    'order__in': order_ids_str
                }
                payment_field_list = ['id', 'payment_type', 'amount', 'created_date', 'order', 'deleted']
                payment_dict = pm_obj.get_data_dict(cr, uid, filter=filter, field_list=payment_field_list, \
                                                       expanded_fields=['order'], context=context)  
                                                       
                # Step 5: Get payout
                po_obj.set_credential(credential)
                filter = {
                    'created_date__gte': start_date.strftime("%Y-%m-%d"),
                    'created_date__lt' : end_date.strftime("%Y-%m-%d"),
                    'establishment': credential_obj.establishment_id
                }
                payout_field_list = ['id', 'amount', 'created_date', 'payout_reason', 'deleted']
                payout_dict = po_obj.get_data_dict(cr, uid, filter=filter, field_list=payout_field_list, \
                                                       expanded_fields=[], context=context) 
                
                # Step 6: Update inventory and accounting
                for order in pos_order_obj.browse(cr, uid, [obj.get('id') for obj in order_dict.values() if obj.get('id')], context=context):
                    if order.state == 'draft':
                        pos_order_obj.action_paid(cr, uid, [order.id], context=context)
                
                # LAST STEP: Fill location from GOOGLE CALENDAR
                self.update_location_from_google_calendar(cr, uid, credential_obj, start_date, end_date, context)
                
                for session in pos_session_obj.browse(cr, uid, context.get('pos_session', []), context=context):
                    pos_session_id = session.id
                    stop_at = session.stop_at
                    pos_session_obj.open_cb(cr, uid, [pos_session_id], context=context)
                    pos_session_obj.signal_workflow(cr, uid, [pos_session_id], 'cashbox_control')
                    # balance end
                    if not till_dict:
                        for detail in session.cash_register_id.details_ids:
                            if detail.pieces == 1.0:
                                self.pool.get('account.cashbox.line').write(cr, uid, [detail.id], {'number_closing': session.cash_register_balance_end})
                    acc_bank_obj.write(cr, uid, [session.cash_register_id.id], {'date': start_date, 'balance_end_real': session.cash_register_balance_end})
                    #pos_session_obj.signal_workflow(cr, uid, [pos_session_id], 'close')  
                    if till_dict:
                        pos_session_obj.write(cr, uid, [pos_session_id], {'stop_at': stop_at}, context=context)
                                    
                rc_obj.message_post(cr, uid, [credential_obj.id], body=_('%s Imported data successfully!' % start_date), context=context)
                #except Exception, e:
                #    rc_obj.message_post(cr, uid, [credential_obj.id], body=_('%s Error: %s' % (start_date, str(e))), context=context)
                #    _logger.exception("Error when importing data from Revel POS and Google Calendar : %s !" % e)
                #    raise e
        return {}
    
    def update_location_from_google_calendar(self, cr, uid, credential_obj, start_date=None, end_date=None, context=None):
        if context is None:
            context = {}
            
        gc_obj = self.pool.get('extended.google.calendar') 
        ro_obj = self.pool.get('revelpos.order')
        
        UTC = pytz.timezone('UTC')

        event_dict = gc_obj.get_event_in_day_dict(cr, uid, start_date=start_date, end_date=end_date, credential=credential_obj, context=context)   
        for single_event_dict in event_dict.values():

            if str(single_event_dict.get('summary', False)).startswith("#"):
                result = {'summary': single_event_dict.get('summary', False)}
                if single_event_dict.get('status') != 'cancelled' and single_event_dict.get('location'):
                    date = None
                    stop = None
                    allday = None
                    if single_event_dict.get('start') and single_event_dict.get('end'):
                        if single_event_dict['start'].get('dateTime', False) and single_event_dict['end'].get('dateTime', False):
                            date = parser.parse(single_event_dict['start']['dateTime'])
                            stop = parser.parse(single_event_dict['end']['dateTime'])
                            date = str(date.astimezone(UTC))[:-6]
                            stop = str(stop.astimezone(UTC))[:-6]
                            allday = False
                        else:
                            date = (single_event_dict['start']['date'])
                            stop = (single_event_dict['end']['date'])
                            d_end = datetime.strptime(stop, DEFAULT_SERVER_DATE_FORMAT)
                            allday = True
                            d_end = d_end + timedelta(days=-1)
                            stop = d_end.strftime(DEFAULT_SERVER_DATE_FORMAT)
                            
                    start_hour  = date[-8:]
                    stop_hour   = stop[-8:]                
                    
                    start_date = datetime.combine(start_date, datetime.min.time())
                    time_start = start_date.replace(hour=int(start_hour[:2])).replace(minute=int(start_hour[4::2])).replace(minute=int(start_hour[7::2]))
                    time_stop = start_date.replace(hour=int(stop_hour[:2])).replace(minute=int(stop_hour[4::2])).replace(minute=int(stop_hour[7::2]))

    
                    result.update ({
                        'start': time_start,
                        'stop': time_stop,
                        'allday': allday,
                        'location': single_event_dict.get('location')
                    })

                    search_ids = self.pool.get('pos.order').search(cr, uid, [('date_order', '>=', time_start.strftime("%Y-%m-%d %H:%M:%S%z")),
                                                                             ('date_order', '<=', time_stop.strftime("%Y-%m-%d %H:%M:%S%z"))], context=context)
                    
                    if search_ids: 
                        self.pool.get('pos.order').write(cr, uid, search_ids, {'location': result['location']}, context=context)
                        
        
                
        
    
