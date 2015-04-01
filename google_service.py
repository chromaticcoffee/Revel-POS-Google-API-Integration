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
import openerp
from openerp import tools
from openerp import SUPERUSER_ID
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, exception_to_unicode

from datetime import datetime, timedelta

import werkzeug.urls
import urllib2
import simplejson

from openerp import http
from openerp.http import request
import openerp.addons.web.controllers.main as webmain
from openerp.addons.web.http import SessionExpiredException
from werkzeug.exceptions import BadRequest

import logging
_logger = logging.getLogger(__name__)
    
class revelpos_google_service(osv.osv_memory):
    _inherit = 'google.service'
    _name = 'extended.google.service'
    
    # If no scope is passed, we use service by default to get a default scope
    def _get_authorize_uri(self, cr, uid, google_credential_id, from_url, service, scope=False, context=None):
        """ This method return the url needed to allow this instance of OpenErp to access to the scope of revelpos specified as parameters """
        
        google_credential = self.pool.get('api.credential').get_client_info(cr, uid, google_credential_id, context=context)
        credential_id = google_credential.id
        client_id = google_credential.google_calendar_client_id
        
        state_obj = dict(d=cr.dbname, s=service, f=from_url, c=credential_id)
        base_url = self.get_base_url(cr, uid, context)  
        
        params = {
            'response_type': 'code',
            'client_id': client_id,
            'credential_id': credential_id,
            'state': simplejson.dumps(state_obj),
            'scope': scope or 'https://www.googleapis.com/auth/%s' % (service,),
            'redirect_uri': base_url + '/extended_google_account/authentication',
            'approval_prompt': 'force',
            'access_type': 'offline'
        }

        uri = self.get_uri_oauth(a='auth') + "?%s" % werkzeug.url_encode(params)
        return uri
    
    def _refresh_google_token_json(self, cr, uid, refresh_token, service, credential=None, context=None):  # exchange_AUTHORIZATION vs Token (service = calendar)
        res = False
        if not credential:
            client_id = self.get_client_id(cr, uid, service, context)
            client_secret = self.get_client_secret(cr, uid, service, context)
        else:
            client_id = credential.google_calendar_client_id
            client_secret = credential.google_calendar_client_secret

        params = {
            'refresh_token': refresh_token,
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'refresh_token',
        }

        headers = {"content-type": "application/x-www-form-urlencoded"}

        try:
            uri = self.get_uri_oauth(a='token')

            data = werkzeug.url_encode(params)
            st, res, ask_time = self._do_request(cr, uid, uri, params=data, headers=headers, type='POST', preuri='', context=context)
            return res
        except urllib2.HTTPError, e:
            if e.code == 400:  # invalid grant
                registry = openerp.modules.registry.RegistryManager.get(request.session.db)
                with registry.cursor() as cur:
                    pass
                    #self.pool['res.users'].write(cur, uid, [uid], {'google_%s_rtoken' % service: False}, context=context)
            error_key = simplejson.loads(e.read()).get("error", "nc")
            _logger.exception("Bad google request : %s !" % error_key)
            error_msg = "Something went wrong during your token generation. Maybe your Authorization Code is invalid or already expired [%s]" % error_key
            raise self.pool.get('res.config.settings').get_config_warning(cr, _(error_msg), context=context)
        return res
    
    def _get_google_token_json(self, cr, uid, credential_id, authorize_code, service, context=None):
        res = False
        base_url = self.get_base_url(cr, uid, context)
        
        #client_id = self.get_client_id(cr, uid, service, context)
        #client_secret = self.get_client_secret(cr, uid, service, context)
        
        google_credential   = self.pool.get('api.credential').get_client_info(cr, uid, credential_id, context=context)
        client_id           = google_credential.google_calendar_client_id
        client_secret       = google_credential.google_calendar_client_secret
        
        params = {
            'code': authorize_code,
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'authorization_code',
            'redirect_uri': base_url + '/extended_google_account/authentication'
        }

        headers = {"content-type": "application/x-www-form-urlencoded"}

        try:
            uri = self.get_uri_oauth(a='token')
            data = werkzeug.url_encode(params)

            st, res, ask_time = self._do_request(cr, uid, uri, params=data, headers=headers, type='POST', preuri='', context=context)

        except urllib2.HTTPError:
            error_msg = "Something went wrong during your token generation. Maybe your Authorization Code is invalid"
            raise self.pool.get('res.config.settings').get_config_warning(cr, _(error_msg), context=context)
        return res
    
    

class revelpos_google_calendar(osv.AbstractModel):
    STR_SERVICE = 'calendar'
    _inherit    = 'google.%s' % STR_SERVICE
    _name       = 'extended.google.%s' % STR_SERVICE
    
    def set_all_tokens(self, cr, uid, credential_id, authorization_code, context=None):
        gs_pool = self.pool['extended.google.service']
        all_token = gs_pool._get_google_token_json(cr, uid, credential_id, authorization_code, self.STR_SERVICE, context=context)

        vals = {}
        vals['google_%s_rtoken' % self.STR_SERVICE] = all_token.get('refresh_token')
        vals['google_%s_token_validity' % self.STR_SERVICE] = datetime.now() + timedelta(seconds=all_token.get('expires_in'))
        vals['google_%s_token' % self.STR_SERVICE] = all_token.get('access_token')
        self.pool['api.credential'].write(cr, SUPERUSER_ID, credential_id, vals, context=context)
    
    def authorize_google_uri(self, cr, uid, google_credential_id, from_url='http://www.openerp.com', context=None):   
        url = self.pool['extended.google.service']._get_authorize_uri(cr, uid, google_credential_id, from_url, self.STR_SERVICE, scope=self.get_calendar_scope(), context=context)
        return url
    
    def need_authorize(self, cr, uid, id, context=None):
        credential = self.pool['api.credential'].browse(cr, uid, int(id), context=context)
        return credential.google_calendar_rtoken is False
    
    def get_timezone_from_google(self, cr, uid, calendar_id, token=False, context=None):
       
        if not token:
            token = self.get_token(cr, uid, context)
            
        params = {
            'access_token': token,
            #'timeMin': self.get_minTime(cr, uid, context=context).strftime("%Y-%m-%dT%H:%M:%S.%fz"),
        }
        
        headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
        
        url = "/calendar/v3/calendars/%s" % calendar_id   
        
        status, content, ask_time = self.pool['google.service']._do_request(cr, uid, url, params, headers, type='GET', context=context)
        
        return content['timeZone'] if content.get('timeZone') else None
    
    def get_event_in_day_dict(self, cr, uid, start_date=False, end_date=False, credential=False, timezone=False, token=False, nextPageToken=False, context=None):
        
        google_events_dict = {}

        DEFAULT_CALENDAR_ID = 'primary'
        
        if credential and credential.google_calendar_rtoken:
        
            if not token:
                token = self.get_token(cr, uid, credential, context)
    
            calendar_id = credential.google_calendar_id if credential.google_calendar_id else DEFAULT_CALENDAR_ID
            
            timezone = self.get_timezone_from_google(cr, uid, calendar_id, token, context) if not timezone else timezone
    
            params = {
                'fields': 'items,nextPageToken',
                'access_token': token,
                'maxResults': 1000,
            }
    
            params['showDeleted'] = True
            
            if not end_date:
                end_date        = datetime.now().date()
            params['timeMax']    = end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            if not start_date:
                start_date      = end_date - timedelta(days=1)
            params['timeMin']    = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            #params['timeZone'] = timezone
                
            headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
            
            url = "/calendar/v3/calendars/%s/events" % calendar_id
            
            if nextPageToken:
                params['pageToken'] = nextPageToken
                
            status, content, ask_time = self.pool['google.service']._do_request(cr, uid, url, params, headers, type='GET', context=context)
            
            #print 'Response: ', content   
            
            for google_event in content['items']:
                google_events_dict[google_event['id']] = google_event
    
            if content.get('nextPageToken'):
                google_events_dict.update(
                    self.get_event_in_day_dict(cr, uid, credential=credential, timezone=timezone, token=token, nextPageToken=content['nextPageToken'], context=context)
                )
                
        else:
            error_msg = "Something went wrong during processing. You need to authorize all Google Credential first."
            raise self.pool.get('res.config.settings').get_config_warning(cr, _(error_msg), context=context)

        return google_events_dict
    
    
    # override Google connection
    def get_token(self, cr, uid, credential, context=None):
        if not credential.google_calendar_token_validity or \
                datetime.strptime(credential.google_calendar_token_validity.split('.')[0], DEFAULT_SERVER_DATETIME_FORMAT) < (datetime.now() + timedelta(minutes=1)):
            self.do_refresh_token(cr, uid, credential, context=context)
            #credential.refresh()
            credential = self.pool.get('api.credential').browse(cr, SUPERUSER_ID, credential.id, context=context)
        return credential.google_calendar_token
    
    
    def do_refresh_token(self, cr, uid, credential=None, context=None):
        gs_pool = self.pool['extended.google.service']

        all_token = gs_pool._refresh_google_token_json(cr, uid, credential.google_calendar_rtoken, self.STR_SERVICE, credential=credential, context=context)
        vals = {}
        vals['google_%s_token_validity' % self.STR_SERVICE] = datetime.now() + timedelta(seconds=all_token.get('expires_in'))
        vals['google_%s_token' % self.STR_SERVICE] = all_token.get('access_token')
        
        self.pool['api.credential'].write(cr, SUPERUSER_ID, credential.id, vals, context=context)
        
        
    
