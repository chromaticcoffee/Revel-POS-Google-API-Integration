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

from openerp.tools.translate import _
from openerp import tools
from openerp import SUPERUSER_ID
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, exception_to_unicode

from datetime import datetime, timedelta

import werkzeug.urls
import urllib2
import simplejson
import pytz

import logging
_logger = logging.getLogger(__name__)

REVEL_POS_API_BASE_URI = 'https://lecamionquifume.revelup.com'
REVEL_POS_API_LIMIT = 500
   
class revelpos_service(osv.osv_memory):
    _name = 'revelpos.service'
    _client_id      = None
    _client_secret  = None
    
    _preURI     = REVEL_POS_API_BASE_URI
    _URI        = ''
    _API_limit  = REVEL_POS_API_LIMIT
    
    def set_credential(self, credential):
        self._client_id      = credential['client_id']
        self._client_secret  = credential['client_secret']
    
    def process_obj(self, cr, uid, revel_order_obj, context=None):
        pass
    
    def save_related_data(self, cr, uid, data_dict, context=None):
        pass
  
    def get_resource_id(self, resource_str): 
        id = None
        if len(resource_str):
            list_numbers = [int(s) for s in resource_str.split('/') if s.isdigit()]
            id = list_numbers[0]
        return id
    
    def get_data_dict(self, cr, uid, filter=False, field_list=[], expanded_fields=[], nextPageURI=False, context=None):
        if context is None:
            context = {}
            
        revel_pos_obj_dict = {}
            
        if self._client_id is not None and self._client_secret is not None:
            params = {}
            
            if not nextPageURI:
                params = {
                          'api_key'     : self._client_id,
                          'api_secret'  : self._client_secret,
                          'format'      : 'json',
                          'limit'       : self._API_limit
                }
                
                if filter:
                    params.update(filter)
                    
                if field_list:
                    params['fields'] = ','.join(field_list)
                    
                if expanded_fields:
                    expand_str = '{'
                    for field in expanded_fields:
                        expand_str += '"%s": 1,' % field
                    expand_str = expand_str[:-1]
                    expand_str += '}'
                    params['expand'] = expand_str

            else:
                self._URI = nextPageURI
                params = {}
            
            data = werkzeug.url_encode(params)
            #print (self._preURI + self._URI + "?" + data)
                
            status, content, ask_time = self._do_request(cr, uid, params, type='GET', context=context)
            
            # TEST PURPOSE
            #status = 418
            
            if int(status) not in (204, 404):
                
                # TEST PURPOSE   
                #content = simplejson.loads(self.SIMULATED_CONTENT)
                
                # TEST PURPOSE
                #if filter and self._URI == '/resources/Product/':
                #    content = ONE_PRODUCT_TEST
                    
                if content.get('meta'):
                    if content['meta'].get('time_zone'):
                        context['tz'] = content['meta']['time_zone']
                        
                if content.get('objects'):
                    for obj in content['objects']:
                        processed_obj = self.process_obj(cr, uid, obj, context=context)
                        if processed_obj:
                            revel_pos_obj_dict[str(obj['id'])] = processed_obj

                # Get next page // NOTE : Exceed limit calls if activated
                if content['meta']['next']:
                    revel_pos_obj_dict.update(
                        self.get_data_dict(cr, uid, nextPageURI=content['meta']['next'], context=context)
                    )
                    
        return revel_pos_obj_dict
    
    def _do_request(self, cr, uid, params={}, headers={}, type='POST', context=None):
        if context is None:
            context = {}

        """ Return a tuple ('HTTP_CODE', 'HTTP_RESPONSE') """
        _logger.debug("Uri: %s - Type : %s - Headers: %s - Params : %s !" % (self._URI, type, headers, werkzeug.url_encode(params) if type == 'GET' else params))

        status = 418
        response = ""
        try:
            if type.upper() == 'GET' or type.upper() == 'DELETE':
                if params:
                    data = werkzeug.url_encode(params)
                    req = urllib2.Request(self._preURI + self._URI + "?" + data)
                else:
                    req = urllib2.Request(self._preURI + self._URI)
            elif type.upper() == 'POST' or type.upper() == 'PATCH' or type.upper() == 'PUT':
                req = urllib2.Request(self._preURI + self._URI, params, headers)
            else:
                raise ('Method not supported [%s] not in [GET, POST, PUT, PATCH or DELETE]!' % (type))
            req.get_method = lambda: type.upper()

            request = urllib2.urlopen(req)
            
            status = request.getcode()

            if int(status) in (204, 404):  # Page not found, no response
                response = False
            else:
                content = request.read()
                response = simplejson.loads(content)
                
            try:
                ask_time = datetime.strptime(request.headers.get('date'), "%a, %d %b %Y %H:%M:%S %Z")
            except:
                ask_time = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        except urllib2.HTTPError, e:
            if e.code in (400, 401, 410):
                raise e

            _logger.exception("Bad request : %s !" % e.read())
            raise self.pool.get('res.config.settings').get_config_warning(cr, _("Something went wrong with your request to Revel POS"), context=context)
        return (status, response, ask_time)
    
    
class revelpos_tax(osv.osv_memory):
    _name = 'revelpos.tax'
    _inherit = 'revelpos.service'
    _URI =  '/resources/Tax/'
    
    def process_obj(self, cr, uid, revel_tax_obj, context=None):
        if context is None:
            context = {}
            
        tax = {}
        
        # Get tax rate with latest effective from
        tax_rate_amount = 0.0
        tax_id = str(revel_tax_obj.get('id'))
        latest_tax_effective_from = datetime.strptime("1990-01-01T00:00:00", "%Y-%m-%dT%H:%M:%S")
        tax_effective_from = None
        if revel_tax_obj['tax_rate']:
            if type(revel_tax_obj['tax_rate']) == list:
                for tax_rate in revel_tax_obj['tax_rate']:
                    try:
                        tax_effective_from = datetime.strptime(tax_rate['effective_from'], "%Y-%m-%dT%H:%M:%S.%f") 
                    except: 
                        tax_effective_from = datetime.strptime(tax_rate['effective_from'], "%Y-%m-%dT%H:%M:%S") 

                    if tax_effective_from > latest_tax_effective_from:
                        tax_rate_amount = tax_rate['tax_rate'] / 100
                        latest_tax_effective_from = tax_effective_from
            else:
                tax_rate_amount = float(revel_tax_obj['tax_rate']) / 100
                tax_id = str(revel_tax_obj['local_tax_id'])
           
        if revel_tax_obj:
            tax = {
                'name'              : revel_tax_obj['name'],
                'description'       : '',
                'revel_tax_id'      : tax_id,
                'type'              : 'percent',
                'amount'            : tax_rate_amount, # Test
                'sequence'          : 1,
                'applicable_type'   : 'true',
                'type_tax_use'      : 'all',
                'active'            : revel_tax_obj.get('active', True)
            }
            
            tax['id'] = self.save_tax(cr, uid, tax, context=context)
            
        return tax
            
    def save_tax(self, cr, uid, tax, context=None):
        if context is None:
            context = {}
            
        rs = None
        tax_obj = self.pool.get('account.tax')
        
        search_condition = []
        search_ids = None
        
        if tax.get('name'):
            search_condition = [('name', '=', tax['name'])]
            search_ids = tax_obj.search(cr, uid, search_condition, context=context)
                
        if search_ids:
            rs = search_ids and search_ids[0] or search_ids
            tax_obj.write(cr, uid, rs, tax, context=context)
        else:
            rs = tax_obj.create(cr, uid, tax, context=context)
            
        return rs
    

class revelpos_modifier(osv.osv_memory):
    _name = 'revelpos.modifier'
    _inherit = 'revelpos.service'
    _URI = '/resources/Modifier/'
    
    def process_obj(self, cr, uid, revel_modifier_obj, context=None):
        if context is None:
            context = {}
            
        # Treat modifier as product
        product = {}
        
        if revel_modifier_obj:
            product = {
                'default_code'  : '%s/' % revel_modifier_obj['id'],
                'name'          : '%s (Modifier)' % (revel_modifier_obj.get('name', 'Unknown')),
                'lst_price'     : float(revel_modifier_obj['price']),
                'type'          : 'consu',
                'taxes_id'      : []
            }
            
            rs = self.save_product(cr, uid, product, context=context)
            if rs is not None:
                product['id'] = rs
                
        return product
    
    def save_product(self, cr, uid, product, context=None):
        if context is None:
            context = {}
            
        rs = None
        product_obj = self.pool.get('product.product')
        
        search_ids = None
        search_condition = []
        if product.get('name'):
                search_condition = [('name', '=', product['name'])]
                search_ids = product_obj.search(cr, uid, search_condition, context=context)
                
        if search_ids:
            # Update existing product
            rs = search_ids and search_ids[0] or search_ids
            proc = product_obj.browse(cr, uid, rs, context=context)
            if proc:
                product['default_code'] = proc.default_code + product.get('default_code', '') if product.get('default_code', '') not in proc.default_code else proc.default_code
                product_obj.write(cr, uid, rs, product, context=context)
        else:
            # Save new product
            rs = product_obj.create(cr, uid, product, context=context)
            
        return rs
    
class revelpos_product(osv.osv_memory):
    _name = 'revelpos.product'
    _inherit = 'revelpos.service'
    _URI =  '/resources/Product/'
    
    def process_obj(self, cr, uid, revel_product_obj, context=None):
        if context is None:
            context = {}
            
        product = {}
        
        if revel_product_obj:
            product = {
                   'default_code'   : str(revel_product_obj['id']),
                   'name'           : revel_product_obj['name'] if 'name' in revel_product_obj else '',
                   'lst_price'      : revel_product_obj['price'],
                   'type'           : 'consu',
                   'taxes_id'       : revel_product_obj['tax']
            }       
            
            product.update(
                self.get_related_data(cr, uid, product, context=context)
            )
            
            rs = self.save_product(cr, uid, product, context=context)
            if rs is not None:
                product['id'] = rs

        return product
    
    def get_related_data(self, cr, uid, product, context=None):
        if context is None:
            context = {}
        rt_obj          = self.pool.get('revelpos.tax')    
        updated_data    = {}
        taxes_list = []
        
        account_tax_obj          = self.pool.get('account.tax')
        
        if product.get('taxes_id'):
            taxes_ids         = account_tax_obj.search(cr, uid, [('name', '=', str(product['taxes_id']['name']))], context=context)
            if taxes_ids: 
                for tax in account_tax_obj.browse(cr, uid, taxes_ids, context=context):
                    taxes_list.append(tax['id'])
            else:
                tax = rt_obj.process_obj(cr, uid, product['taxes_id'], context=context)
                taxes_list.append(tax['id'])
        updated_data['taxes_id'] = [(6, 0, taxes_list)]
        
        return updated_data
    
    def save_product(self, cr, uid, product, context=None):
        if context is None:
            context = {}
            
        rs = None
        product_obj = self.pool.get('product.product')
        
        search_ids = None
        search_condition = []
        if product.get('name'):
            search_condition = [('name', '=', product['name'])]
            search_ids = product_obj.search(cr, uid, search_condition, context=context)
                
        if search_ids:
            # Update existing product
            rs = search_ids and search_ids[0] or search_ids
            product_obj.write(cr, uid, rs, product, context=context)
        else:
            # Save new product
            rs = product_obj.create(cr, uid, product, context=context)
            
        return rs
    
    
class revelpos_orderline(osv.osv_memory):
    _name = 'revelpos.order.line'
    _inherit = 'revelpos.service'
    _URI =  '/resources/OrderItem/'
    _API_limit = 1000
    
    def process_obj(self, cr, uid, revel_orderline_obj, context=None):
        if context is None:
            context = {}
        product_obj     = self.pool.get('product.product')
        if not revel_orderline_obj or revel_orderline_obj.get('deleted') == True:
            return {}
        
        order_line = {
            'price_unit'            : float(revel_orderline_obj['price']),
            'qty'                   : float(revel_orderline_obj['quantity']),
            'revel_pos_orderline_id': str(revel_orderline_obj['id']),
            'is_revel_orderline'    : True,
            'tax_included'          : revel_orderline_obj['tax_included'],
            'voided'                : True if revel_orderline_obj['void_ref_uuid'] else False,
        }
        
        order_line.update(
            self.get_related_data(cr, uid, revel_orderline_obj, context=context)           
        )   
                    
        if order_line.get('product_id'):
            self.save_orderline(cr, uid, order_line, context=context)
        
        if revel_orderline_obj.get('modifieritems'):
            modifier_ids = []
            for modifier_item in revel_orderline_obj['modifieritems']:
                revel_modifier_id = str(self.get_resource_id(modifier_item['modifier']))
                
                modifier_ids = product_obj.search(cr, uid, [('default_code', 'ilike', '%s/' % revel_modifier_id)], context=context)
                if modifier_ids:
                    modifier_id = modifier_ids and modifier_ids[0] or modifier_ids
                    
                    order_line_w_modifier = {
                        'price_unit'            : float(modifier_item['modifier_price']),
                        'qty'                   : float(modifier_item['qty']),
                        'revel_pos_orderline_id': str('M%s' % modifier_item['id']),
                        'is_revel_orderline'    : True,
                        'tax_included'          : True,
                        'voided'                : order_line.get('voided'),
                        'product_id'            : modifier_id,
                        'order_id'              : order_line.get('order_id'),
                        'revel_taxes_ids'       : order_line.get('revel_taxes_ids', [])
                    }
                    # Saving order line w modifier
                    self.save_orderline(cr, uid, order_line_w_modifier, context=context)  
        
        return order_line
    
    def get_related_data(self, cr, uid, revel_orderline_obj, context=None):
        if context is None:
            context = {}
            
        product_id = None
        order_id = None
        
        updated_data    = {}
        
        product_obj     = self.pool.get('product.product')
        pos_order_obj   = self.pool.get('pos.order')
        rp_obj          = self.pool.get('revelpos.product')
        rt_obj          = self.pool.get('revelpos.tax')
        
        revel_order_id = str(revel_orderline_obj['order']['id'])
        if revel_order_id:
            order_ids = pos_order_obj.search(cr, uid, [('revel_pos_id', '=', revel_order_id)], context=context)
                
            if order_ids:
                order_id = order_ids and order_ids[0] or order_ids
                
                updated_data['order_id'] = order_id
        
        # Some order lines somehow doesn't contain any product, which should be eliminated
        if revel_orderline_obj.get('product'):
            revel_product_name = str(revel_orderline_obj['product']['name'])
            
            if revel_product_name:
                product_ids = product_obj.search(cr, uid, [('name', '=', revel_product_name)], context=context)
        
                if product_ids:
                    product_id = product_ids and product_ids[0] or product_ids
                else:
                    # Product doesn't exist in Odoo, need to get from API result
                    product = rp_obj.process_obj(cr, uid, revel_orderline_obj['product'], context=context)
                    product_id = product['id']
                
                    
            updated_data['product_id'] = product_id
        
        # Save taxes 
        if revel_orderline_obj.get('applied_taxes'):
            taxes_ids = []
            for revel_tax in revel_orderline_obj['applied_taxes']:
                revel_tax_name = str(revel_tax['name'])
                revel_tax_rate = float(revel_tax['tax_rate'])/100
                
                tax_ids = self.pool.get('account.tax').search(cr, uid, [('name', '=', revel_tax_name),('amount','=',revel_tax_rate)], context=context)
                if tax_ids:
                    tax_id = tax_ids and tax_ids[0] or tax_ids
                    taxes_ids.append(tax_id)
                else:
                    tax = rt_obj.process_obj(cr, uid, revel_tax, context=context)
                    taxes_ids.append(tax['id'])
                    
            updated_data['revel_taxes_ids'] = [(6, 0, taxes_ids)]
                 
        return updated_data
    
    def save_orderline(self, cr, uid, orderline, context=None):
        if context is None:
            context = {}
            
        rs = None
        orderline_obj = self.pool.get('pos.order.line')

        search_ids = None
        search_condition = []
        
        if orderline.get('revel_pos_orderline_id'):
            search_condition = [('revel_pos_orderline_id', '=', orderline['revel_pos_orderline_id'])]
            search_ids = orderline_obj.search(cr, uid, search_condition, context=context)
                
        if search_ids:
            # Update existing orderline
            rs = search_ids and search_ids[0] or search_ids
            orderline_obj.write(cr, uid, rs, {'voided': orderline.get('voided')}, context=context)
        else:
            # Save new orderline
            rs = orderline_obj.create(cr, uid, orderline, context=context)
            
        return rs
    

class revelpos_order(osv.osv_memory):
    _name = 'revelpos.order'
    _inherit = 'revelpos.service'
    _URI =  '/resources/Order/'
    
    def process_obj(self, cr, uid, revel_order_obj, context=None):
        if context is None:
            context = {}
        
        order = {}       

        # order is closed, paid, not deleted and not created to split bills
        if revel_order_obj and not revel_order_obj.get('bill_parent') and revel_order_obj.get('closed') == True and revel_order_obj.get('is_unpaid') == False:
            date_order = datetime.strptime(revel_order_obj['created_date'], "%Y-%m-%dT%H:%M:%S") if revel_order_obj.get('created_date') else ''
            if context.get('tz') and date_order:
                time_zone = pytz.timezone(context.get('tz'))
                date_order = time_zone.localize(date_order)            
                date_order_utc = pytz.utc.normalize(date_order.astimezone(pytz.utc))
            else:
                date_order_utc = date_order
            
            session_id = context.get('pos_session') and context.get('pos_session')[0] or 1            
            if date_order_utc:
                for session in self.pool.get('pos.session').browse(cr, uid, context.get('pos_session', []), context=context):
                    start_at = pytz.utc.localize(datetime.strptime(session.start_at, "%Y-%m-%d %H:%M:%S"))
                    stop_at = pytz.utc.localize(datetime.strptime(session.stop_at, "%Y-%m-%d %H:%M:%S"))
                    if start_at <= date_order_utc <= stop_at:
                        session_id = session.id
                        break
            pricelist_id = self.pool.get('pos.session').browse(cr, uid, session_id, context=context).config_id.pricelist_id  
            order = {
                'revel_pos_id'         : str(revel_order_obj['id']) if 'id' in revel_order_obj else None,
                'date_order'           : date_order_utc,
                'session_id'           : session_id, 
                'user_id'              : revel_order_obj['created_by'] if 'created_by' in revel_order_obj else None,
                'pricelist_id'         : pricelist_id and pricelist_id.id or False
            }
            
            order.update(
                 self.save_related_data(cr, uid, order, context=context)        
            )
            
            order['id'] = self.save_order(cr, uid, order, context=context)

        return order
    
    def save_related_data(self, cr, uid, order, context=None):
        if context is None:
            context = {}
            
        updated_data = {}
        
        res_users_obj = self.pool.get('res.users')
        ru_obj = self.pool.get('revelpos.user')
        
        user = ru_obj.process_obj(cr, uid, order['user_id'], context=context)
        user_id = ru_obj.save_user(cr, uid, user, context=context)
        
        if user_id:
            updated_data['user_id'] = user_id
        
        return updated_data
    
    def save_order(self, cr, uid, pos_order, context=None):
        if context is None:
            context = {}
            
        rs = None
        pos_order_obj = self.pool.get('pos.order')
        
        search_ids = None
        search_condition = []
        if pos_order.get('revel_pos_id'):
            search_condition = [('revel_pos_id', '=', pos_order['revel_pos_id'])]
            search_ids = pos_order_obj.search(cr, uid, search_condition, context=context)
                
        if search_ids:
            rs = search_ids and search_ids[0] or search_ids
            pos_order_obj.write(cr, uid, rs, {'date_order': pos_order.get('date_order'), 'user_id': pos_order.get('user_id')}, context=context)
        else:
            rs = pos_order_obj.create(cr, uid, pos_order, context=context)
            #pos_order_obj.action_paid(cr, uid, [rs], context=context)
            
        return rs
    
class revelpos_user(osv.osv_memory):
    _name = 'revelpos.user'
    _inherit = 'revelpos.service'
    _URI =  '/enterprise/User/'
    
    def process_obj(self, cr, uid, revel_user_obj, context=None):
        if context is None:
            context = {}

        user = {}

        if revel_user_obj:
            user = {
                    'name': '%s %s' % (revel_user_obj.get('first_name', ''), revel_user_obj.get('last_name', '')),
                    'login': revel_user_obj.get('username', ''),
                    #'active': revel_user_obj.get('is_active', False),
            }
            
            user.update(
                self.save_related_data(cr, uid, user, context=context)
            )
            
        return user
    
    def save_related_data(self, cr, uid, user, context=None):
        if context is None:
            context = {}
            
        updated_data = {}
        
        rp_obj          = self.pool.get('revelpos.partner')
        
        partner     = rp_obj.process_obj(cr, uid, user, context=context)
        partner_id  = rp_obj.save_partner(cr, uid, partner, context=context)
        
        if partner_id:
            updated_data['partner_id'] = partner_id

        return updated_data
    
    def save_user(self, cr, uid, user, context=None):
        if context is None:
            context = {}
            
        rs = None
        res_users_obj = self.pool.get('res.users')
        
        search_condition = []
        search_ids = None
        
        if user.get('login'):
            search_condition = [('login', '=', user['login'])]
            search_ids = res_users_obj.search(cr, uid, search_condition, context=context)
                
        if search_ids:
            rs = search_ids and search_ids[0] or search_ids
            res_users_obj.write(cr, uid, rs, user, context=context)
        else:
            rs = res_users_obj.create(cr, uid, user, context=context)
            
        return rs
    
    
class revelpos_partner(osv.osv_memory):
    _name = 'revelpos.partner'
    _inherit = 'revelpos.service'
    
    def process_obj(self, cr, uid, partner_obj, context=None):
        if context is None:
            context = {}
            
        res_partner_obj = self.pool.get('res.partner')
        partner = {}
        
        if partner_obj:
            partner = {
                'name': partner_obj['name'] if 'name' in partner_obj else '',
                'email': partner_obj['login'] if 'login' in partner_obj else ''
            }
            
        return partner 
    
    def save_partner(self, cr, uid, partner, context=None):
        if context is None:
            context = {}
        
        rs = None  
        res_partner_obj = self.pool.get('res.partner')
        
        search_condition = []
        search_ids = None
        
        if partner.get('email'):
            search_condition = [('email', '=', partner['email'])] 
            search_ids = res_partner_obj.search(cr, uid, search_condition, context=context)
                
        if search_ids:
            rs = search_ids and search_ids[0] or search_ids
            res_partner_obj.write(cr, uid, rs, partner, context=context)
        else:
            rs = res_partner_obj.create(cr, uid, partner, context=context)
            
        return rs
            
class revelpos_payment(osv.osv_memory):
    _name = 'revelpos.payment'
    _inherit = 'revelpos.service'
    _URI =  '/resources/Payment/'
    
    def process_obj(self, cr, uid, payment_obj, context=None):
        if context is None:
            context = {}
            
        payment = {}
        property_obj = self.pool.get('ir.property')
        if payment_obj and payment_obj.get('deleted') != True:
            payment_date = datetime.strptime(payment_obj['created_date'], "%Y-%m-%dT%H:%M:%S") if 'created_date' in payment_obj else ''
            if context.get('tz') and payment_date:
                time_zone = pytz.timezone(context.get('tz'))
                payment_date = time_zone.localize(payment_date)            
                payment_date_utc = pytz.utc.normalize(payment_date.astimezone(pytz.utc))
            else:
                payment_date_utc = payment_date
            account_def = property_obj.get(cr, uid, 'property_account_receivable', 'res.partner', context=context)    
            payment = {
                'payment_type' : payment_obj['payment_type'] if 'payment_type' in payment_obj else '',
                'revel_order_id': payment_obj['order']['id'] if 'order' in payment_obj else '',
                'amount': payment_obj['amount'] if 'amount' in payment_obj else '',
                'date': payment_date_utc,
                'name': str(payment_obj.get('id', '')),
                'partner_id': False,
                'account_id': (account_def and account_def.id) or False,                                
            }
            
            rs = None  
            account_journal_obj = self.pool.get('account.journal')
            
            search_condition = []
            search_ids = None
            
            if payment.get('payment_type'):
                search_condition = [('revel_payment_id', '=', payment['payment_type'])] 
                search_ids = account_journal_obj.search(cr, uid, search_condition, context=context)
                    
            if search_ids:
                payment['journal_id'] = type(search_ids) == list and search_ids[0] or search_ids
                self.save_payment(cr, uid, payment, context=context)
            else:
                raise osv.except_osv(_('Error!'), _('Missing payment type %s' % (payment.get('payment_type'))))
            
        return payment         
    
    def save_payment(self, cr, uid, payment, context=None):
        if context is None:
            context = {}
        
        rs = None
        pos_order_obj = self.pool.get('pos.order')
        statement_line_obj = self.pool.get('account.bank.statement.line')
        search_ids = None
        search_condition = []
        if payment.get('revel_order_id'):
            search_condition = [('revel_pos_id', '=', payment['revel_order_id'])]
            search_ids = pos_order_obj.search(cr, uid, search_condition, context=context)
                
        if search_ids:
            rs = type(search_ids) == list and search_ids[0] or search_ids 
            order = pos_order_obj.browse(cr, uid, rs, context=context)
            payment['pos_statement_id'] = order.id
            payment['name'] = order.name + ': ' + payment.get('name', '')
            payment['ref'] = order.session_id.name
            for statement in order.session_id.statement_ids:
                if statement.journal_id.id == payment.get('journal_id'):
                    payment['statement_id'] = statement.id
                    break
                    
            search_condition = [('name', '=', payment['name'])]
            search_ids = statement_line_obj.search(cr, uid, search_condition, context=context)        
            if search_ids:
                rs = type(search_ids) == list and search_ids[0] or search_ids 
                statement_line_obj.write(cr, uid, [rs], payment, context=context)
            else:
                statement_line_obj.create(cr, uid, payment, context=context)
        else:
            raise osv.except_osv(_('Error!'), _('Missing order ID %s' % (payment.get('revel_order_id'))))
        return rs
 
class revelpos_till(osv.osv_memory):
    _name = 'revelpos.till'
    _inherit = 'revelpos.service'
    _URI =  '/resources/Till/'
    
    def process_obj(self, cr, uid, till_obj, context=None):
        if context is None:
            context = {}
            
        till = {}
        
        if till_obj.get('closed'):
            open_date = datetime.strptime(till_obj['opened'], "%Y-%m-%dT%H:%M:%S") if 'opened' in till_obj else ''
            close_date = datetime.strptime(till_obj['closed'], "%Y-%m-%dT%H:%M:%S") if 'closed' in till_obj else ''
            if context.get('tz'):
                time_zone = pytz.timezone(context.get('tz'))
                if open_date:
                    open_date = time_zone.localize(open_date)            
                    open_date = pytz.utc.normalize(open_date.astimezone(pytz.utc))
                if close_date:
                    close_date = time_zone.localize(close_date)            
                    close_date = pytz.utc.normalize(close_date.astimezone(pytz.utc))
                            
            till = {
                'start_at': open_date,
                'stop_at': close_date,
                'revel_balance_start' : till_obj.get('amount_till_set'),
                'revel_balance_end_real': till_obj.get('amount_present'),
                'user_id': 1,
                'config_id': context.get('config_id', 1),
                'state': 'closed'
            }
            
            till['id'] = self.save_till(cr, uid, till, context=context)
            
        return till         
    
    def save_till(self, cr, uid, till, context=None):
        if context is None:
            context = {}
        
        pos_session_obj = self.pool.get('pos.session')
        acc_bank_obj = self.pool.get('account.bank.statement')
        
        pos_session_id = pos_session_obj.create(cr, uid, till, context=context)
        for session in pos_session_obj.browse(cr, uid, [pos_session_id], context=context):
            for detail in session.cash_register_id.details_ids:
                if detail.pieces == 1.0:
                    self.pool.get('account.cashbox.line').write(cr, uid, [detail.id], {'number_opening': till.get('revel_balance_start',0.0), 'number_closing': till.get('revel_balance_end_real',0.0)})
            acc_bank_obj.write(cr, uid, [session.cash_register_id.id], {'balance_end_real': session.cash_register_balance_end})
        pos_session_obj.write(cr, uid, [pos_session_id], {'state': 'closed'})                
        return pos_session_id
        
    def get_data_dict(self, cr, uid, filter=False, field_list=[], expanded_fields=[], nextPageURI=False, start_date=None, end_date=None, context=None):
        if context is None:
            context = {}
            
        revel_pos_obj_dict = {}
        limit = 20   
        if self._client_id is not None and self._client_secret is not None:
            params = {}            
            if not nextPageURI:
                params = {
                          'api_key'     : self._client_id,
                          'api_secret'  : self._client_secret,
                          'format'      : 'json',
                          'limit'       : limit
                }                
                if filter:
                    params.update(filter)                    
                if field_list:
                    params['fields'] = ','.join(field_list)                    
                if expanded_fields:
                    expand_str = '{'
                    for field in expanded_fields:
                        expand_str += '"%s": 1,' % field
                    expand_str = expand_str[:-1]
                    expand_str += '}'
                    params['expand'] = expand_str
            else:
                self._URI = nextPageURI
                params = {}
            
            data = werkzeug.url_encode(params)
            status, content, ask_time = self._do_request(cr, uid, params, type='GET', context=context)
            
            # TEST PURPOSE
            #status = 418
            
            if int(status) not in (204, 404):                
                # TEST PURPOSE   
                #content = simplejson.loads(self.SIMULATED_CONTENT)
                if content.get('meta'):
                    if content['meta'].get('time_zone'):
                        context['tz'] = content['meta']['time_zone']
                    if content.get('next'):
                        old_offset = content.get('offset', 0)
                        offset = content.get('total_count', 0) - limit
                        nextPageURI = nextPageURI.replace(('offset=%d' % old_offset), ('offset=%d' % offset))
                        revel_pos_obj_dict = self.get_data_dict(cr, uid, nextPageURI=nextPageURI, context=context)
                    else:
                        if content.get('objects'):
                            time_zone = pytz.timezone(context.get('tz', 'UTC'))
                            for obj in content['objects']:
                                if obj.get('created_date'):
                                    created_date = time_zone.localize(datetime.strptime(obj['created_date'], "%Y-%m-%dT%H:%M:%S"))
                                    if start_date and end_date and start_date <= created_date.date()  <= end_date:
                                        processed_obj = self.process_obj(cr, uid, obj, context=context)
                                        if processed_obj:
                                            revel_pos_obj_dict[str(obj['id'])] = processed_obj

        return revel_pos_obj_dict
    
class revelpos_payout(osv.osv_memory):
    _name = 'revelpos.payout'
    _inherit = 'revelpos.service'
    _URI =  '/resources/Payout/'
    
    def process_obj(self, cr, uid, payout_obj, context=None):
        if context is None:
            context = {}
            
        payout = {}
        
        if payout_obj and payout_obj.get('deleted') != True: 
            created_date = datetime.strptime(payout_obj['created_date'], "%Y-%m-%dT%H:%M:%S") if payout_obj.get('created_date') else ''
            if context.get('tz') and created_date:
                time_zone = pytz.timezone(context.get('tz'))
                created_date = time_zone.localize(created_date)            
                created_date_utc = pytz.utc.normalize(created_date.astimezone(pytz.utc))
            else:
                created_date_utc = created_date
                
            session_id = context.get('pos_session') and context.get('pos_session')[0] or False  
            if session_id:
                session_id = self.pool.get('pos.session').browse(cr, uid, session_id, context=context)
            if created_date_utc:
                for session in self.pool.get('pos.session').browse(cr, uid, context.get('pos_session', []), context=context):
                    start_at = pytz.utc.localize(datetime.strptime(session.start_at, "%Y-%m-%d %H:%M:%S"))
                    stop_at = pytz.utc.localize(datetime.strptime(session.stop_at, "%Y-%m-%d %H:%M:%S"))
                    if start_at <= created_date_utc <= stop_at:
                        session_id = session
                        break
            
            if session_id:            
                payout = {
                    'statement_id': session_id.cash_register_id.id,
                    'journal_id': session_id.cash_register_id.journal_id.id,
                    'amount': - payout_obj.get('amount', 0.0),
                    'account_id': session_id.cash_register_id.journal_id.internal_account_id.id,
                    'ref': '',
                    'name': payout_obj.get('payout_reason', 'Unknown'),
                    'date': created_date_utc and created_date_utc.date()
                }
                
                payout['id'] = self.save_payout(cr, uid, payout, context=context)
            
        return payout         
    
    def save_payout(self, cr, uid, payout, context=None):
        if context is None:
            context = {}
        
        return self.pool.get('account.bank.statement.line').create(cr, uid, payout, context=context)
 