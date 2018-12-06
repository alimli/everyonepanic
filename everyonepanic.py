import contextlib
import json
import os
import urllib2
import webapp2
from twilio.rest import TwilioRestClient
import urlparse

# Calls you when your sites go down.
# License is GPLv3.
# Author: Eric Jiang <eric@doublemap.com>

TWILIO_SID = os.environ['TWILIO_SID']
TWILIO_TOKEN = os.environ['TWILIO_TOKEN']
TWILIO_FROM = os.environ['TWILIO_FROM']
CALLEES = os.environ['CALLEES'].split(',')

UPTIME_ROBOT_KEY = os.environ['UPTIME_ROBOT_KEY']
UPTIME_ROBOT = "https://api.uptimerobot.com/getMonitors?apiKey=" + UPTIME_ROBOT_KEY + "&format=json&noJsonCallback=1"
UPTIME_CRITICAL_ALARMS = {}
if 'UPTIME_CRITICAL_ALARMS' in os.environ:
    UPTIME_CRITICAL_ALARMS = os.environ['UPTIME_CRITICAL_ALARMS'].split(',')

# what's our app name?
APP_HOSTNAME = "YOUR_APP_HERE.appspot.com"
if 'APP_HOSTNAME' in os.environ:  # try environment
    APP_HOSTNAME = os.environ['APP_HOSTNAME']
else:  # try getting it from app engine
    try:
        from google.appengine.api.app_identity import get_application_id
        APP_HOSTNAME = get_application_id() + ".appspot.com"
    except ImportError:
        pass


class MainPage(webapp2.RequestHandler):
    def get(self):
        self.response.headers['Content-Type'] = 'text/plain'
        self.response.write('Hi, this thing will call you if uptime robot reports down sites.')


def get_uptime_status():
    with contextlib.closing(urllib2.urlopen(UPTIME_ROBOT)) as ustream:
        resp = json.load(ustream)

    downsites = []
    for m in resp['monitors']['monitor']:
        if m['status'] == "9" and ( not UPTIME_CRITICAL_ALARMS or (m['friendlyname'] in UPTIME_CRITICAL_ALARMS) ):  # 9 == "Down", 8 == "Seems down"
            downsites.append(m['friendlyname'])
    return {"total": len(resp['monitors']['monitor']), "down": len(downsites), "downsites": downsites}


def trigger_call(recp):
    client = TwilioRestClient(TWILIO_SID, TWILIO_TOKEN)
    call = client.calls.create(url=("https://%s/downmessage" % APP_HOSTNAME),
        to=recp, from_=TWILIO_FROM, status_callback=("https://%s/statuscallback" % APP_HOSTNAME),
        status_callback_event=['completed'], status_callback_method='POST')
    print(call)

class CheckUptimes(webapp2.RequestHandler):
    def get(self):
        self.response.headers['Content-Type'] = 'text/plain'
        res = get_uptime_status()

        self.response.write("Critical Alarms: %s\n" % ", ".join(UPTIME_CRITICAL_ALARMS))
        critical_alarm_count = UPTIME_CRITICAL_ALARMS and len(UPTIME_CRITICAL_ALARMS) or res['total']
        self.response.write("%d sites being monitored. %d of them are critical.\n" % (res['total'], critical_alarm_count))
        if res['down'] != 0:
            self.response.write("Everybody panic!\n")
            for site in res['downsites']:
                self.response.write("%s is down.\n" % site)
            trigger_call(CALLEES[0])
        else:
            self.response.write("Everything seems fine\n")


class DowntimeMessage(webapp2.RequestHandler):
    def post(self):
        self.response.headers['Content-Type'] = "text/xml"
        res = get_uptime_status()
        if res['down'] != 0:
            self.response.write("""<?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Say voice="alice" loop="10">Everyone panic! %s</Say>
            </Response>""" % " ".join(map(lambda s: ("%s is down." % s), res['downsites'])))
        else:
            self.response.write("""<?xml version="1.0" encoding="UTF-8"?>
            <Response>
                <Say voice="alice">False alarm. %d of %d sites are down.</Say>
            </Response>""" % (res['down'], res['total']))


class StatusCallBack(webapp2.RequestHandler):
    def post(self):
        url_params = urlparse.parse_qs(self.request.body)
        to = url_params['To'][0]
        call_status =  url_params['CallStatus'][0]
        try:
            to_index = CALLEES.index(to)
        except ValueError:
            to_index = 0

        print("Call to %s completed as %s" % (to, call_status))
        if call_status in ['busy', 'no-answer']:
            next_to_index = (to_index + 1) % len(CALLEES)
            print("Calling %s\n" % CALLEES[next_to_index])
            trigger_call(CALLEES[next_to_index])


application = webapp2.WSGIApplication([
    ('/', MainPage),
    ('/checksites', CheckUptimes),
    ('/downmessage', DowntimeMessage),
    ('/statuscallback', StatusCallBack),
], debug=True)
