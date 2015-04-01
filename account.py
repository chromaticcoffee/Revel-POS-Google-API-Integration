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

class revelpos_account(osv.osv):
    _inherit = "account.tax"
    _description = 'Add a field to refer to RevelPOS tax resource'
                
    _columns = {
        'revel_tax_id': fields.char('Revel ID'),
    }

class account_journal(osv.osv):
    _inherit = 'account.journal'
    _columns = {
        'revel_payment_id': fields.char('Revel Payment Code')
    }
        
        
    
