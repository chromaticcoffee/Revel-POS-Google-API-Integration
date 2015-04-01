import simplejson
import urllib
import openerp
from openerp import http
from openerp.http import request
import openerp.addons.web.controllers.main as webmain
from openerp.addons.web.http import SessionExpiredException
from werkzeug.exceptions import BadRequest
import werkzeug.utils

class extended_google_auth(http.Controller):
    
    @http.route('/extended_google_account/authentication', type='http', auth="none")
    def oauth2callback(self, **kw):
        """ This route/function is called by Google when user Accept/Refuse the consent of Google """
        
        state = simplejson.loads(kw['state'])
        dbname = state.get('d')
        service = state.get('s')
        url_return = state.get('f')
        credential_id = state.get('c')
        
        
        print url_return
        print 'Credential ne', credential_id
        print 'Code ne', kw['code']
        
        registry = openerp.modules.registry.RegistryManager.get(dbname)
        with registry.cursor() as cr:
            if kw.get('code',False):
                registry.get('extended.google.%s' % service).set_all_tokens(cr,request.session.uid,credential_id,kw['code'])
                return werkzeug.utils.redirect(url_return)
            elif kw.get('error'):
                return werkzeug.utils.redirect("%s%s%s" % (url_return ,"?error=" , kw.get('error')))
            else:
                return werkzeug.utils.redirect("%s%s" % (url_return ,"?error=Unknown_error"))


class extended_google_calendar_controller(http.Controller):

    @http.route('/google_credential/authorize', type='json', auth='user')
    def authorize(self, arch, fields, model, **kw):
        """
            This route/function is called when we want to synchronize openERP calendar with Google Calendar
            Function return a dictionary with the status :  need_config_from_admin, need_auth, need_refresh, success if not calendar_event
            The dictionary may contains an url, to allow OpenERP Client to redirect user on this URL for authorization for example
        """

        if model == 'api.credential':
            gs_obj = request.registry['extended.google.service']
            gc_obj = request.registry['extended.google.calendar']
            gcd_obj = request.registry['api.credential']

            # Checking that admin have already configured Google API for google synchronization !
            client_id = gs_obj.get_client_id(request.cr, request.uid, 'calendar', context=kw.get('local_context'))
            
            google_credential = gcd_obj.get_client_info(request.cr, request.uid, kw.get('id'), context=kw.get('local_context'))

            client_id = google_credential.google_calendar_client_id
            print google_credential.google_calendar_client_secret

            if not client_id or client_id == '':
                return {
                    "status": "need_config_from_admin",
                    "url": ''
                }

            # Checking that user have already accepted OpenERP to access his calendar !
            if gc_obj.need_authorize(request.cr, request.uid, kw.get('id'), context=kw.get('local_context')):
                url = gc_obj.authorize_google_uri(request.cr, request.uid, kw.get('id'), from_url=kw.get('fromurl'), context=kw.get('local_context'))
                return {
                    "status": "need_auth",
                    "url": url
                }

            # If App authorized, and user access accepted, We launch the synchronization
            # return gc_obj.synchronize_events(request.cr, request.uid, [], context=kw.get('local_context'))

        return {"status": "success"}

    @http.route('/google_credential/remove_references', type='json', auth='user')
    def remove_references(self, model, **kw):
        """
            This route/function is called when we want to remove all the references between one calendar OpenERP and one Google Calendar
        """
        status = "NOP"
        if model == 'calendar.event':
            gc_obj = request.registry['google.calendar']
            # Checking that user have already accepted OpenERP to access his calendar !
            if gc_obj.remove_references(request.cr, request.uid, context=kw.get('local_context')):
                status = "OK"
            else:
                status = "KO"
        return {"status": status}
