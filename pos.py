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
from openerp import SUPERUSER_ID
from openerp.tools.translate import _

from datetime import datetime, timedelta
import pytz
from pytz import timezone

from dateutil import parser
from openerp import tools
import openerp.addons.decimal_precision as dp

class revelpos_pos_orderline(osv.osv):
    _inherit = "pos.order.line"
    
    def _revel_amount_line_all(self, cr, uid, ids, field_names, arg, context=None):
        res = dict([(i, {}) for i in ids])
        account_tax_obj = self.pool.get('account.tax')
        cur_obj = self.pool.get('res.currency')
        for line in self.browse(cr, uid, ids, context=context):
            taxes_ids = []

            if not line.is_revel_orderline:
                taxes_ids = [ tax for tax in line.product_id.taxes_id if tax.company_id.id == line.order_id.company_id.id ]
                
            else:

                taxes_ids = [ tax for tax in line.revel_taxes_ids]
                for tax in taxes_ids:
                    tax.price_include = line.tax_included
                
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)

            taxes = account_tax_obj.compute_all(cr, uid, taxes_ids, price, line.qty, product=line.product_id, partner=line.order_id.partner_id or False)

            cur = line.order_id.pricelist_id.currency_id
            
            res[line.id]['price_subtotal'] = cur_obj.round(cr, uid, cur, taxes['total'])
            res[line.id]['price_subtotal_incl'] = cur_obj.round(cr, uid, cur, taxes['total_included'])
            res[line.id]['price_tax'] = res[line.id]['price_subtotal_incl'] - res[line.id]['price_subtotal']
            res[line.id]['applied_taxes'] = ', '.join([str(tax.name) for tax in taxes_ids])
        return res
    
    _columns = {
        'is_revel_orderline': fields.boolean('Is Revel Order Line'),
        'revel_pos_orderline_id': fields.char('Revel Order ID'),
        'tax_included': fields.boolean('Tax Included'),
        'revel_taxes_ids': fields.many2many('account.tax', 'orderline_taxes_rel',
            'id', 'tax_id', 'Customer Taxes',
            domain=[('parent_id','=',False),('type_tax_use','in',['sale','all'])]),
        'price_subtotal': fields.function(_revel_amount_line_all, multi='pos_order_line_amount', string='Subtotal w/o Tax', store=True),
        'price_subtotal_incl': fields.function(_revel_amount_line_all, multi='pos_order_line_amount', string='Subtotal', store=True),
        'price_tax': fields.function(_revel_amount_line_all, multi='pos_order_line_amount', string='Tax Amount', store=True),
        'voided': fields.boolean('Voided'),
        'applied_taxes': fields.function(_revel_amount_line_all, multi='pos_order_line_amount', string='Taxes', type='char', store=True),
    } 
    
    _defaults = {
        'is_revel_orderline': lambda *a: False,
        'tax_included': lambda *a: False,
        'voided': lambda *a: False,
    }


class revelpos_pos_order(osv.osv):
    _inherit = "pos.order"
    _description = 'Add a button to test fetching data from Revel POS system. NOTE: Change to cron job later.'
    
    def _get_shift(self, cr, uid, ids, field_name=None, arg=False, context=None):
        res = {}
        
        for order in self.browse(cr, uid, ids, context=context):         
            date_order = fields.datetime.context_timestamp(cr, uid, datetime.strptime(order.date_order, tools.DEFAULT_SERVER_DATETIME_FORMAT), context=context)

            if date_order.hour >= 0 and date_order.hour < 11:
                res[order.id] = 'Nuit'
                break
            elif date_order.hour >= 11 and date_order.hour < 15:
                res[order.id] = 'Midi'
                break
            elif date_order.hour >= 15 and date_order.hour < 19:
                res[order.id] = 'Après-midi'
                break
            else:
                res[order.id] = 'Soir'
                break

        return res  
    
    def _revel_amount_all(self, cr, uid, ids, name, args, context=None):
        cur_obj = self.pool.get('res.currency')
        res = {}
        for order in self.browse(cr, uid, ids, context=context):
            res[order.id] = {
                'amount_paid': 0.0,
                'amount_return':0.0,
                'amount_tax':0.0,
            }
            val1 = val2 = 0.0
            cur = order.pricelist_id.currency_id
            for payment in order.statement_ids:
                res[order.id]['amount_paid'] +=  payment.amount
                res[order.id]['amount_return'] += (payment.amount < 0 and payment.amount or 0)
            for line in order.lines:
                if not line.voided:
                    val1 += line.price_subtotal_incl
                    val2 += line.price_subtotal
            res[order.id]['amount_tax'] = cur_obj.round(cr, uid, cur, val1-val2)
            res[order.id]['amount_total'] = cur_obj.round(cr, uid, cur, val1)
        return res
        
    _columns = {
        'location': fields.text('Location'),
        'revel_pos_id': fields.char('Revel Order No.'),
        'shift': fields.function(_get_shift, type='char', readonly=True, string='Shift', method=True),  
        'amount_tax': fields.function(_revel_amount_all, string='Taxes', digits_compute=dp.get_precision('Account'), multi='all'),
        'amount_total': fields.function(_revel_amount_all, string='Total', multi='all'),
        'amount_paid': fields.function(_revel_amount_all, string='Paid', states={'draft': [('readonly', False)]}, readonly=True, digits_compute=dp.get_precision('Account'), multi='all'),
        'amount_return': fields.function(_revel_amount_all, 'Returned', digits_compute=dp.get_precision('Account'), multi='all'),        
    }

    def _create_account_move_line(self, cr, uid, ids, session=None, move_id=None, context=None):
        # Tricky, via the workflow, we only have one id in the ids variable
        """Create a account move line of order grouped by products or not."""
        account_move_obj = self.pool.get('account.move')
        account_period_obj = self.pool.get('account.period')
        account_tax_obj = self.pool.get('account.tax')
        property_obj = self.pool.get('ir.property')
        cur_obj = self.pool.get('res.currency')

        #session_ids = set(order.session_id for order in self.browse(cr, uid, ids, context=context))

        if session and not all(session.id == order.session_id.id for order in self.browse(cr, uid, ids, context=context)):
            raise osv.except_osv(_('Error!'), _('Selected orders do not have the same session!'))

        grouped_data = {}
        have_to_group_by = session and session.config_id.group_by or False

        def compute_tax(amount, tax, line):
            if amount > 0:
                tax_code_id = tax['base_code_id']
                tax_amount = line.price_subtotal * tax['base_sign']
            else:
                tax_code_id = tax['ref_base_code_id']
                tax_amount = line.price_subtotal * tax['ref_base_sign']

            return (tax_code_id, tax_amount,)

        for order in self.browse(cr, uid, ids, context=context):
            if order.account_move:
                continue
            if order.state != 'paid':
                continue

            current_company = order.sale_journal.company_id

            group_tax = {}
            account_def = property_obj.get(cr, uid, 'property_account_receivable', 'res.partner', context=context)

            order_account = order.partner_id and \
                            order.partner_id.property_account_receivable and \
                            order.partner_id.property_account_receivable.id or \
                            account_def and account_def.id or current_company.account_receivable.id

            if move_id is None:
                # Create an entry for the sale
                move_id = account_move_obj.create(cr, uid, {
                    'ref' : order.name,
                    'journal_id': order.sale_journal.id,
                }, context=context)

            def insert_data(data_type, values):
                # if have_to_group_by:

                sale_journal_id = order.sale_journal.id
                period = account_period_obj.find(cr, uid, context=dict(context or {}, company_id=current_company.id))[0]

                # 'quantity': line.qty,
                # 'product_id': line.product_id.id,
                values.update({
                    'date': order.date_order[:10],
                    'ref': order.name,
                    'partner_id': order.partner_id and self.pool.get("res.partner")._find_accounting_partner(order.partner_id).id or False,
                    'journal_id' : sale_journal_id,
                    'period_id' : period,
                    'move_id' : move_id,
                    'company_id': current_company.id,
                })

                if data_type == 'product':
                    key = ('product', values['partner_id'], values['product_id'], values['debit'] > 0)
                elif data_type == 'tax':
                    key = ('tax', values['partner_id'], values['tax_code_id'], values['debit'] > 0)
                elif data_type == 'counter_part':
                    key = ('counter_part', values['partner_id'], values['account_id'], values['debit'] > 0)
                else:
                    return

                grouped_data.setdefault(key, [])

                # if not have_to_group_by or (not grouped_data[key]):
                #     grouped_data[key].append(values)
                # else:
                #     pass

                if have_to_group_by:
                    if not grouped_data[key]:
                        grouped_data[key].append(values)
                    else:
                        current_value = grouped_data[key][0]
                        current_value['quantity'] = current_value.get('quantity', 0.0) +  values.get('quantity', 0.0)
                        current_value['credit'] = current_value.get('credit', 0.0) + values.get('credit', 0.0)
                        current_value['debit'] = current_value.get('debit', 0.0) + values.get('debit', 0.0)
                        current_value['tax_amount'] = current_value.get('tax_amount', 0.0) + values.get('tax_amount', 0.0)
                else:
                    grouped_data[key].append(values)

            #because of the weird way the pos order is written, we need to make sure there is at least one line, 
            #because just after the 'for' loop there are references to 'line' and 'income_account' variables (that 
            #are set inside the for loop)
            #TOFIX: a deep refactoring of this method (and class!) is needed in order to get rid of this stupid hack
            assert order.lines, _('The POS order must have lines when calling this method')
            # Create an move for each order line

            cur = order.pricelist_id.currency_id
            for line in order.lines:
                tax_amount = 0
                taxes = []
                if not line.is_revel_orderline:
                    for t in line.product_id.taxes_id:
                        if t.company_id.id == current_company.id:
                            taxes.append(t)                    
                else:
                    taxes = [ tax for tax in line.revel_taxes_ids]
                    for tax in taxes:
                        tax.price_include = line.tax_included
                
                computed_taxes = account_tax_obj.compute_all(cr, uid, taxes, line.price_unit * (100.0-line.discount) / 100.0, line.qty)['taxes']

                for tax in computed_taxes:
                    tax_amount += cur_obj.round(cr, uid, cur, tax['amount'])
                    group_key = (tax['tax_code_id'], tax['base_code_id'], tax['account_collected_id'], tax['id'])

                    group_tax.setdefault(group_key, 0)
                    group_tax[group_key] += cur_obj.round(cr, uid, cur, tax['amount'])

                amount = line.price_subtotal

                # Search for the income account
                if  line.product_id.property_account_income.id:
                    income_account = line.product_id.property_account_income.id
                elif line.product_id.categ_id.property_account_income_categ.id:
                    income_account = line.product_id.categ_id.property_account_income_categ.id
                else:
                    raise osv.except_osv(_('Error!'), _('Please define income '\
                        'account for this product: "%s" (id:%d).') \
                        % (line.product_id.name, line.product_id.id, ))

                # Empty the tax list as long as there is no tax code:
                tax_code_id = False
                tax_amount = 0
                while computed_taxes:
                    tax = computed_taxes.pop(0)
                    tax_code_id, tax_amount = compute_tax(amount, tax, line)

                    # If there is one we stop
                    if tax_code_id:
                        break

                # Create a move for the line
                insert_data('product', {
                    'name': line.product_id.name,
                    'quantity': line.qty,
                    'product_id': line.product_id.id,
                    'account_id': income_account,
                    'credit': ((amount>0) and amount) or 0.0,
                    'debit': ((amount<0) and -amount) or 0.0,
                    'tax_code_id': tax_code_id,
                    'tax_amount': tax_amount,
                    'partner_id': order.partner_id and self.pool.get("res.partner")._find_accounting_partner(order.partner_id).id or False
                })

                # For each remaining tax with a code, whe create a move line
                for tax in computed_taxes:
                    tax_code_id, tax_amount = compute_tax(amount, tax, line)
                    if not tax_code_id:
                        continue

                    insert_data('tax', {
                        'name': _('Tax'),
                        'product_id':line.product_id.id,
                        'quantity': line.qty,
                        'account_id': income_account,
                        'credit': 0.0,
                        'debit': 0.0,
                        'tax_code_id': tax_code_id,
                        'tax_amount': tax_amount,
                        'partner_id': order.partner_id and self.pool.get("res.partner")._find_accounting_partner(order.partner_id).id or False
                    })

            # Create a move for each tax group
            (tax_code_pos, base_code_pos, account_pos, tax_id)= (0, 1, 2, 3)

            for key, tax_amount in group_tax.items():
                tax = self.pool.get('account.tax').browse(cr, uid, key[tax_id], context=context)
                insert_data('tax', {
                    'name': _('Tax') + ' ' + tax.name,
                    'quantity': line.qty,
                    'product_id': line.product_id.id,
                    'account_id': key[account_pos] or income_account,
                    'credit': ((tax_amount>0) and tax_amount) or 0.0,
                    'debit': ((tax_amount<0) and -tax_amount) or 0.0,
                    'tax_code_id': key[tax_code_pos],
                    'tax_amount': tax_amount,
                    'partner_id': order.partner_id and self.pool.get("res.partner")._find_accounting_partner(order.partner_id).id or False
                })

            # counterpart
            insert_data('counter_part', {
                'name': _("Trade Receivables"), #order.name,
                'account_id': order_account,
                'credit': ((order.amount_total < 0) and -order.amount_total) or 0.0,
                'debit': ((order.amount_total > 0) and order.amount_total) or 0.0,
                'partner_id': order.partner_id and self.pool.get("res.partner")._find_accounting_partner(order.partner_id).id or False
            })

            order.write({'state':'done', 'account_move': move_id})

        all_lines = []
        for group_key, group_data in grouped_data.iteritems():
            for value in group_data:
                all_lines.append((0, 0, value),)
        if move_id: #In case no order was changed
            self.pool.get("account.move").write(cr, uid, [move_id], {'line_id':all_lines}, context=context)

        return True
    
class revelpos_pos_session(osv.osv):
    _inherit = "pos.session"
    def _check_pos_config(self, cr, uid, ids, context=None):
        for session in self.browse(cr, uid, ids, context=None):
            domain = [
                ('state', 'not in', ('closed','closing_control')),
                ('config_id', '=', session.config_id.id)
            ]
            count = self.search_count(cr, uid, domain, context=context)
            if count>1:
                return False
        return True
        
    _constraints = [
        (_check_pos_config, "You cannot create two active sessions related to the same point of sale!", ['config_id']),
    ]
