# itamoba
#
# Copyright Douglas Reed 2025
#
# A script for showing if there is any music on BBC Alba

# *** IMPORTS ***
from machine import Pin
import time
import ntptime
import network
import requests
import json

# *** CONSTANTS ***
GPIO_GREEN = 15
GPIO_YELLOW = 13
GPIO_ORANGE = 9
GPIO_RED = 5

BBC_SCHEDULE_URL_PREFIX='https://www.bbc.co.uk/iplayer/guide/bbcalba/'
# Need to set a valid user agent string or the BBC server will return 403 Access Denied
# You may occasionally need to update this string. Point an up-to-date web browser at http://httpbin.io/user-agent
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"}

# LED patterns for different conditions
#   [Green,Yellow,Orange,Red]
ALL_ON = [1,1,1,1]
ALL_OFF = [0,0,0,0]

# Music status
MUSIC_NOW = [1,0,0,0]
MUSIC_SOON = [0,1,0,0]
MUSIC_LATER = [0,0,1,0]
MUSIC_NEVER = [0,0,0,1]

# error conditions
CONFIG_ERROR = [0,1,1,1] # xYOR - Problem reading config - Have you set up config file? (see below)
WIFI_ERROR = [0,0,1,1] # xxOR - Problem connecting to WiFi - Is it on? have you entered SSID and password correctly?
INET_ERROR = [0,1,0,1] # xYxR - Problem getting network time or problem accessing BBC Schedule page - Check that network's live using another device
PARSE_ERROR = [0,1,1,0] # xYOx - Problem parsing schedule page - Has the format changed?

# *** GLOBAL VARIABLES ***
leds = [Pin(GPIO_GREEN, Pin.OUT),
        Pin(GPIO_YELLOW, Pin.OUT),
        Pin(GPIO_ORANGE, Pin.OUT),
        Pin(GPIO_RED, Pin.OUT)]

led_refresh_interval = 10
schedule_refresh_interval = 3600

# *** FUNCTION DEFINITIONS ***

def set_leds(pattern=[0,0,0,0]):
  for l in range(4):
    leds[l].value(pattern[l])

def parse_schedule(schedule_page):
  print("Parsing schedule page...")
  buf = bytearray(2048)
  schedule_bytes = bytearray()
  while True:
    numbytes = schedule_page.raw.readinto(buf)
    start_index = buf.find(b'{"navigation"')
    if start_index != -1:
      print("Found start!")
      end_index = buf[start_index:].find(b';</script>')
      if end_index != -1:
        print("Found end!")
        schedule_bytes = buf[start_index:end_index]
        break
      else:
        schedule_bytes = buf[start_index:]
        while True:
          numbytes = schedule_page.raw.readinto(buf)
          end_index = buf.find(b';</script>')
          if end_index != -1:
            print("Found end!")
            schedule_bytes.extend(buf[:end_index])
            break
          else:
            schedule_bytes.extend(buf)
          if numbytes < len(buf):
            break
    if numbytes < len(buf):
      break

  schedule_string = schedule_bytes.decode('utf8')
  schedule_json = json.loads(schedule_string)
  programmes = schedule_json["schedule"]["items"]
  music_times = []
  for item in programmes:
    if item["props"]["label"] == "Music":
      # Timestamps are provided by the BBC schedule in the format 2025-10-12T14:10:00.000Z
      # Fortunately they are given in UTC, so I don't have to worry about daylight savings time! 
      s = item["meta"]["scheduledStart"]
      start_time = time.mktime([int(s[0:4]), int(s[5:7]), int(s[8:10]), int(s[11:13]), int(s[14:16]), int(s[17:19]),0,0])
      st = time.gmtime(start_time)
      e = item["meta"]["scheduledEnd"]
      end_time = time.mktime([int(e[0:4]), int(e[5:7]), int(e[8:10]), int(e[11:13]), int(e[14:16]), int(e[17:19]),0,0])
      et = time.gmtime(end_time)
      print(f"Music found from {st[3]:02d}:{st[4]:02d}:{st[5]:02d} to {et[3]:02d}:{et[4]:02d}:{et[5]:02d}!")
      music_times.append([start_time, end_time])
  
  return music_times


# *** INITIALISATION ***

# Startup animation
set_leds([0,0,0,1])
time.sleep(0.25)
set_leds([0,0,1,1])
time.sleep(0.25)
set_leds([0,1,1,1])
time.sleep(0.25)
set_leds(ALL_ON)
time.sleep(1)

# configure with the following commands in the REPL:
#
# >>> import json
# >>> config={'wifissid':'[ssid]','wifipass':'[pass]','routeone':'[NN]','routetwo':'[NN]'}
# >>> f = open('config.json', 'w')
# >>> f.write(json.dumps(config))
# >>> f.close()
#

# Read config

try:
  f=open("config.json","r")
  config=json.loads(f.read())
  f.close()
except:
  set_leds(CONFIG_ERROR)
  raise RuntimeError("Couldn't read config")

# Connect to WiFi
print('connecting to WIFI with SSID: ',config['wifissid'])
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(config['wifissid'], config['wifipass'])

# Wait for connection
while True:
  if wlan.status() < 0 or wlan.status() >= 3:
    break
  print('waiting for WiFi connection...')
  time.sleep(1)

# Handle connection error
if wlan.status() != 3:
  set_leds(WIFI_ERROR)
  raise RuntimeError('Network connection failed')
else:
  print('connected to WiFi')
  wlan_status = wlan.ifconfig()
  print( 'ip = ' + wlan_status[0] )

# Get network time and set clock
while True:
  try:
    ntptime.settime()
  except:
    set_leds(INET_ERROR)
    print('Failed to get network time. Retrying...')
    time.sleep(1)
  else:
    t = time.gmtime()
    print("Time now is: {:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(t[0],t[1],t[2],t[3],t[4],t[5]))
    break

set_leds(ALL_OFF)

last_schedule_update = 0
last_led_update = 0
schedule_downloaded = False

# *** MAIN LOOP ***
while True:
  now = time.time()
  if now > last_schedule_update + schedule_refresh_interval:
    print("Refreshing schedule")
    t = time.gmtime()
    today = "{:04d}{:02d}{:02d}".format(t[0],t[1],t[2])
    try:
      schedule_page = requests.get(BBC_SCHEDULE_URL_PREFIX + today, headers = HEADERS, stream = True)
    except:
      set_leds(INET_ERROR)
      print("Couldn't download schedule page")
    else:
      print("Schedule page downloaded")
      print("Response:", schedule_page.status_code)
      music_times = parse_schedule(schedule_page)
      schedule_page.close()
      last_schedule_update = now
      schedule_downloaded = True
  if schedule_downloaded and now > last_led_update + led_refresh_interval:
    music_status = MUSIC_NEVER
    for music in reversed(music_times):
      if music[1] > now:
        if music[0] <= now:
          music_status = MUSIC_NOW
        elif music[0] <= now + 3600:
          music_status = MUSIC_SOON
        elif music[0] > now + 3600:
          music_status = MUSIC_LATER
        
    set_leds(music_status)
    print(music_status)
    last_led_update = now

  time.sleep(1)

