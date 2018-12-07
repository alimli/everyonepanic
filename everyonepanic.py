import contextlib
import json
import os
import urllib2
import webapp2
from twilio.rest import TwilioRestClient
import urlparse
import datetime
import pytz

# Calls you when your sites go down.
# License is GPLv3.
# Author: Eric Jiang <eric@doublemap.com>

TWILIO_SID = os.environ['TWILIO_SID']
TWILIO_TOKEN = os.environ['TWILIO_TOKEN']
TWILIO_FROM = os.environ['TWILIO_FROM']
CALLEES = os.environ['CALLEES'].split(',')

UPTIME_ROBOT_KEY = os.environ['UPTIME_ROBOT_KEY']
# Statuses= 9 Fetches Only Down Monitors
# Logs = 1 Includes Log in the response so that down period can be calculated
UPTIME_ROBOT = "https://api.uptimerobot.com/getMonitors?apiKey=" + UPTIME_ROBOT_KEY + "&format=json&noJsonCallback=1&logs=1"
UPTIME_CRITICAL_MONITORS = {}
if 'UPTIME_CRITICAL_MONITORS' in os.environ:
    UPTIME_CRITICAL_MONITORS = os.environ['UPTIME_CRITICAL_MONITORS'].split(',')

DOWN_TIME_MINUTES = 60
if 'DOWN_TIME_MINUTES' in os.environ:
     DOWN_TIME_MINUTES = int(os.environ['DOWN_TIME_MINUTES'])

DOWN_TIME_TZ = pytz.timezone('Europe/Istanbul')
if 'DOWN_TIME_TZ' in os.environ:
     DOWN_TIME_TZ = pytz.timezone(os.environ['DOWN_TIME_TZ'])


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
    if(resp['monitors']):
        for m in resp['monitors']['monitor']:
            if m['status'] == "9" and ( not UPTIME_CRITICAL_MONITORS or (m['friendlyname'] in UPTIME_CRITICAL_MONITORS) ):  # 9 == "Down", 8 == "Seems down"
                print(m)
                last_down_time = datetime.datetime.strptime( m['log'][0]['datetime'], "%m/%d/%Y %H:%M:%S")
                now = datetime.datetime.now(DOWN_TIME_TZ).replace(tzinfo=None)
                if (now - last_down_time) > datetime.timedelta(minutes=DOWN_TIME_MINUTES):
                    downsites.append(m['friendlyname'])
        return {"total": len(resp['monitors']['monitor']), "down": len(downsites), "downsites": downsites}
    else:
        return {"total": 0, "down": 0, "downsites": downsites}

def trigger_call(recp):
    client = TwilioRestClient(TWILIO_SID, TWILIO_TOKEN)
    call = client.calls.create(url=("https://%s/downmessage" % APP_HOSTNAME),
        to=recp, from_=TWILIO_FROM, status_callback=("https://%s/statuscallback" % APP_HOSTNAME),
        status_callback_event=['completed'], status_callback_method='POST',
        machine_detection='Enable') # machine_detection : Ensure call not answered by Voicemail
    print(call)

class CheckUptimes(webapp2.RequestHandler):
    def get(self):
        self.response.headers['Content-Type'] = 'text/plain'
        res = get_uptime_status()

        self.response.write("Critical Monitors: %s\n" % ", ".join(UPTIME_CRITICAL_MONITORS))
        critical_alarm_count = UPTIME_CRITICAL_MONITORS and len(UPTIME_CRITICAL_MONITORS) or res['total']
        self.response.write("%d sites being monitored. %d of them are critical.\n" % (res['total'], critical_alarm_count))
        if res['down'] != 0:
            self.response.write("Everybody panic!\n")
            for site in res['downsites']:
                self.response.write("%s is down more than %d minutes.\n" % (site, DOWN_TIME_MINUTES))
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
        print url_params
        to = url_params['To'][0]
        call_status =  url_params['CallStatus'][0]
        answered_by = url_params['AnsweredBy'][0]
        try:
            to_index = CALLEES.index(to)
        except ValueError:
            to_index = 0

        print("Call to %s completed as %s and answered by %s" % (to, call_status, answered_by))
        if call_status in ['busy', 'no-answer', 'failed'] or answered_by != 'human':
            next_to_index = (to_index + 1) % len(CALLEES)
            print("Calling %s\n" % CALLEES[next_to_index])
            trigger_call(CALLEES[next_to_index])


application = webapp2.WSGIApplication([
    ('/', MainPage),
    ('/checksites', CheckUptimes),
    ('/downmessage', DowntimeMessage),
    ('/statuscallback', StatusCallBack),
], debug=True)
