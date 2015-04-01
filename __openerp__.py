# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
#
#    Copyright (C) 2014 Novobi LLC (<http://novobi.com>)
#
##############################################################################


{
    'name': 'Revel POS Integration',
    'category': '', 
    'version': '1.0',
    'description': """
    """,
    'author': 'Novobi LLC',
    'website': 'http://www.novobi.com',
    'depends': ['base', 'web', 'base_setup', 'point_of_sale', 'google_account','google_calendar'],
    'qweb': ['static/src/xml/*.xml'],
    'data': [
         'pos_view.xml',
         'account_view.xml',
         'api_credential_view.xml',
         'views/google_calendar.xml',
         'wizard/schedulers_all_view.xml'
    ],    
    'installable': True,
    'auto_install': False
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
