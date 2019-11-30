from flask import Flask, request, send_from_directory, g

import threading
from queue import Queue, PriorityQueue
from http.client import HTTPConnection
import os, sys, time, logging
from datetime import datetime
from xml.etree import ElementTree
from xml.etree.ElementTree import ElementTree as ETree
from xml.dom import minidom 
from urllib.parse import unquote
import uuid, csv
import errno
import json
from nools_gen import generate_nools
from pprint import pprint
import colorama
from colorama import Fore, Back, Style
import atexit
import signal

colorama.init(autoreset=True)

HOST_DOMAIN = '127.0.0.1' #Use this instead of localhost on windows
# PORT = 8000

post_queue = Queue(maxsize=0)
write_queue = Queue(maxsize=0)

# session_events = {}
session_data_lock = threading.Lock()
context_data_lock = threading.Lock()
write_lock = threading.Lock()
session_dicts = {}

# IGNORE_TOOL_MESSAGES = False

POST_THREADS = 4
WRITE_THREADS = 1


#defining function to run on shutdown
def cleanup():
    post_queue.join()
    write_queue.join()
    log_file_handle.close()
    print("CLEANUP")
#Register the function to be called on exit
atexit.register(cleanup)
signal.signal(signal.SIGTERM, cleanup)



def check_started(host,port):
    started = False
    while not started:
        try:
            conn = HTTPConnection("%s:%d" % (host,port))
            j_msg = json.dumps({"type" : "info", "message" : "Server Started"})
            conn.request("PRINT", "/", j_msg)
            resp = conn.getresponse()
            if resp.status == 200:
                started = True
            
        except:
            time.sleep(.001)
    print("HOST SERVER STARTED")


class HostServer(Flask):
  def run(self, host=None, port=None, debug=None, load_dotenv=True, **options):
    thread = threading.Thread(target=lambda : check_started(host,port))
    thread.start() 
    super(HostServer, self).run(host=host, port=port, debug=debug, load_dotenv=load_dotenv, **options)
    

app = HostServer(__name__,static_folder='../')



# output.write("Anon Student Id\tSession Id\tTime\tStudent Response Type\tTutor Response Type\tLevel (Unit)\tProblemName\tStep Name\tSelection\tAction\tInput\tFeedback Text\tOutcome\n");
LOG_HEADERS = {"user_guid"              :"Anon Student Id",
               "session_id"             :"Session Id",
               "transaction_id"         :"Transaction Id",
               "tutor_event_time"       :"Time",
               "timezone"               :"Time Zone",
               "student_resp_type"      :"Student Response Type",
               "tutor_resp_type"        :"Tutor Response Type",
               "level"                  :"Level (Domain)",
               "problem_name"           :"Problem Name",
               "step_id"                :"Step Name",
               "selection"              :"Selection",
               "action"                 :"Action",
               "input"                  :"Input",
               "tutor_advice"           :"Feedback Text",
               "action_evaluation"      :"Outcome",
               "problem_context"        :"CF (Problem Context)",
               }

session_default_dict =  {key: None for key in LOG_HEADERS.values()}
output_file_path = None
tool_dict = {}

def _fill_from_elm(log_dict, elm,typ='tutor'):
    if(elm.tag == "custom_field"):
        name = next(elm.iter("name")).text
        if(name in LOG_HEADERS):
            if(name == "tutor_event_time"):
                dt = datetime.strptime(next(elm.iter("value")).text, "%Y-%m-%d %H:%M:%S.%f %Z")#--> microseconds works on this one
                t = time.strptime(next(elm.iter("value")).text, "%Y-%m-%d %H:%M:%S.%f %Z") #--> timezone works on this one
                log_dict[LOG_HEADERS["tutor_event_time"]] = dt.strftime("%Y-%m-%d %H:%M:%S.") + str(dt.microsecond // 1000)
                log_dict[LOG_HEADERS["timezone"]] = time.strftime("%Z", t)
                # print(log_dict[LOG_HEADERS["tutor_event_time"]])
            else:
                log_dict[LOG_HEADERS[name]] = next(elm.iter("value")).text 
    elif(elm.tag == "event_descriptor" and typ == "tool"):
        log_dict[LOG_HEADERS["selection"]] = next(elm.iter("selection")).text 
        log_dict[LOG_HEADERS["action"]] = next(elm.iter("action")).text 
        log_dict[LOG_HEADERS["input"]] = next(elm.iter("input")).text 
    elif(elm.tag == "semantic_event"):
        rt = elm.attrib["name"]
        log_dict[LOG_HEADERS["transaction_id"]] = elm.attrib["transaction_id"]
        if(typ == "tool"):
            log_dict[LOG_HEADERS["student_resp_type"]] = rt
        else:
            log_dict[LOG_HEADERS["tutor_resp_type"]] = rt
        # log_dict[LOG_HEADERS["student_resp_type"]] = {"RESULT":"ATTEMPT","HINT_MSG":"HINT_REQUEST"}.get(trt,None)

    elif(elm.tag == "dataset"):
        for level in elm.iter("level"):
            name = next(level.iter("name")).text
            level_header = "Level (%s)" % level.attrib["type"]
            if(level_header in LOG_HEADERS.values()):
                log_dict[level_header] = name
            elm = level

        problem = next(elm.iter("problem"))
        log_dict[LOG_HEADERS["problem_name"]] = next(problem.iter("name")).text 
        log_dict[LOG_HEADERS["problem_context"]] = next(problem.iter("context")).text 

    elif(elm.tag in LOG_HEADERS):
        log_dict[LOG_HEADERS[elm.tag]] = elm.text

    else:
        for key,value in elm.attrib.items():
            if(key in LOG_HEADERS):
                log_dict[LOG_HEADERS[key]] = value       



def shutdown_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()

def _print_and_resp(message=None,m_type="default",outmode=sys.stdout):
    # content_length = int(handler.headers['Content-Length']) # <--- Gets the size of data
    # post_data = handler.rfile.read(content_length) # <--- Gets the data itself
    if(message is None):
        post_data = json.loads(request.get_data())
        # print(post_data)
        m_type = post_data.get('type', 'default').lower()
        message = post_data.get('message', None)
    
    # print("message",message)
    if(message is not None):
        if m_type == 'correct':
            print(Back.GREEN + Fore.BLACK  + message)
        elif m_type == 'incorrect':
            print(Back.RED + Fore.BLACK + message)
        elif m_type == 'example':
            print(Back.BLUE + Fore.YELLOW  +  message)#, file=outmode)
        elif m_type == 'info':
            print(Back.WHITE + Fore.BLACK + message)
        elif m_type == 'warning':
            print(Back.BLACK + Fore.YELLOW + message)#, file=outmode)
        elif m_type == 'error':
            print(Back.BLACK + Fore.RED + message)#, file=outmode)
        else:
            print(message)#, file=outmode)
    # handler.send_response(200)
    # handler.end_headers()

# f = with open(output_file_path, 'a', newline='') as f: 


def write_rows(rows,count):
    global write_lock
    global csv_writer
    global log_file_handle
    # print("WRITE(%s) %d" %( count, len(rows)))
    write_lock.acquire()
    for row in rows:
        csv_writer.writerow(row)
    write_lock.release()
    log_file_handle.flush()

    
    # print("END", count)

write_count = -1

def write_problem(session_id,context_id,order=None):
    global output_file_path
    # global session_events
    global session_dicts

    global write_count
    write_count += 1
    
        

    
    # pprint("BLAMP", session_dicts[session_id])
    # session_data_lock.acquire()
    c_dict = session_dicts[session_id]['logs'][context_id]
    tool_logs = c_dict['tool']
    tutor_logs = c_dict['tutor']
    session_start_dict = session_dicts[session_id]['start']
    context_dict = c_dict['context']
    # del session_dicts[session_id]
    # del session_events[session_id]
    # session_data_lock.release()
    # print("COUNT(%d) %d:%d" % (write_count, len(tool_logs.keys()),len(tutor_logs.keys())))
    if(order is None):
        order = list(tool_logs.keys())

    rows = []
    default_dict = {**{key: None for key in LOG_HEADERS.values()},
                     **session_start_dict,
                     **context_dict}
    for t_id in order:
        rows.append({**default_dict,
                     **tool_logs.get(t_id,{}),
                     **tutor_logs.get(t_id,{})})

    write_rows(rows,write_count)

    del session_dicts[session_id]['logs'][context_id]
    # write_thread = threading.Thread(target=lambda :write_rows(rows))
    # write_thread.start()
context_counter = 0

def get_context_dict(session_id,context_id):
    global context_data_lock
    global session_dict
    global context_counter
    context_data_lock.acquire()

    if(context_id not in session_dicts[session_id]['logs']):
        logs = session_dicts[session_id]['logs']
        c_dict = {}
        logs[context_id] = c_dict
        c_dict["context"] = {}
        c_dict["tool"] = {}
        c_dict["tutor"] = {}
        c_dict["priority"] = context_counter

        context_counter += 1
    else:
        c_dict = session_dicts[session_id]['logs'][context_id]

    context_data_lock.release()
    return c_dict



#####################
def handle_post(post_data):
    # x = post_item.xml_tree
    # session_id = post_item.session_id
    # print("POST")
    global session_data_lock
    global context_counter

    # global session_events
    global session_dicts
    # print(post_data)
    # print(minidom.parseString(post_data).toprettyxml())

    # https://github.com/CMUCTAT/CTAT/wiki/Logging-Documentation

    # print("S:%s" % session_id)

    envelope = ElementTree.fromstring(post_data)


    for x in envelope.iter():

        session_id = x.attrib["session_id"]

        session_data_lock.acquire()
        if(session_id not in session_dicts):
            session_dict = {}
            session_dict['logs'] = {}
            session_dict['start'] = {}
            session_dicts[session_id] = session_dict

        session_data_lock.release()

        # post_queue.put(PostItem(x,
        #                         session_id,
        #                         session_dicts[session_id]["priority"]))    

        # session_buffer.append(x)
        # print(minidom.parseString(ElementTree.tostring(x, encoding='utf8', method='xml')).toprettyxml())

        # print("TAG",x.tag)
        if(x.tag == "log_session_start"):
            # print("Message Type: ", x.tag)
            session_start_dict = {}
            _fill_from_elm(session_start_dict, x)
            session_dicts[session_id]['start'] = session_start_dict
            # session_start_event.set()

            # print(minidom.parseString(ElementTree.tostring(x, encoding='utf8', method='xml')).toprettyxml())


        
        elif(x.tag == "log_action"):

            # print("#")
            # session_start_event.wait()
            # print("%")


            # session_default_dict = session_dicts[session_id]['default']

            # print("log action attr:",x.attrib)
            # print(unquote(x.text))
            payload = ElementTree.fromstring(unquote(x.text))

            # print(minidom.parseString(ElementTree.tostring(payload, encoding='utf8', method='xml')).toprettyxml())

            for msg in payload.iter("context_message"):
                context_id = msg.attrib['context_message_id']
                # print("context_message attr:",msg.attrib)
                # print("Message Type: ", "context_message")
                context_dict = {}
                _fill_from_elm(context_dict, msg)
                for elm in list(msg):
                    _fill_from_elm(context_dict,elm)


                c_dict = get_context_dict(session_id,context_id)
                c_dict['context'] = context_dict
                # context_data_lock.acquire()

                # session_context_event.set()
                # pprint(session_default_dict)
                # print()

            # print("@")
            # session_context_event.wait()
            # print("&")
            
            
            # if(not IGNORE_TOOL_MESSAGES):
            for msg in payload.iter("tool_message"):
                # tool_queue.put((session_id,msg))
                context_id = msg.attrib['context_message_id']

                tool_dict = {}
                for elm in list(msg):
                    _fill_from_elm(tool_dict, elm,"tool")

                c_dict = get_context_dict(session_id,context_id)
                c_dict['tool'][tool_dict['Transaction Id']] = tool_dict
                # session_dicts[session_id]['tool'] = tool_dict
                
                    # print("TOOL TRANS", msg.attrib)


            for msg in payload.iter("tutor_message"):
                context_id = msg.attrib['context_message_id']
                log_dict = {}

                sel = None
                for elm in list(msg):
                    _fill_from_elm(log_dict, elm,"tutor")
                    if(elm.tag == "event_descriptor"):
                        sel = next(elm.iter("selection")).text 
                    # print("tag", elm.tag)
                # print("SWERPT",log_dict,log_dict['Transaction Id'])
                # print("SEL",sel)

                c_dict = get_context_dict(session_id,context_id)
                c_dict['tutor'][log_dict['Transaction Id']] = log_dict
                # session_dicts[session_id]['tutor'][log_dict['Transaction Id']] = log_dict

                if(sel == "done" and log_dict.get("Outcome",None) == "CORRECT"):
                    timer = threading.Timer(1,lambda :write_queue.put((session_id,context_id)))
                    timer.start()
                    # session_end_event.set()
                    # print("START WRITE")
                    # write_thread = threading.Thread(target=lambda :write_session(session_id))
                    # write_thread.start()

                # tutor_queue.put((session_id,msg))
                # print("tutor_message attr:",msg.attrib)
                # print("Message Type: ", "tutor_message")

                # log_dict = session_default_dict.copy()
                
                    
                    # thread = threading.Thread(target=lambda : )
                    # thread.start() 

                # print("t_id",log_dict.get(LOG_HEADERS['transaction_id'],"bloop"))

                # print("------MESSAGE-------")
                # mstring = ElementTree.tostring(msg, encoding='utf8', method='xml')                    
                # print(minidom.parseString(mstring).toprettyxml())
                # print("------LOG_DICT-------")
                # for key,val in log_dict.items():
                #     print(key, ":", val)
                # print("-------------------")

                # print("------TOOL_DICT-------")
                # for key,val in tool_dict.items():
                #     print(key, ":", val)
                # print("-------------------")

                # if(not IGNORE_TOOL_MESSAGES):
                #     if(tool_dict != None and log_dict != None and 
                #         tool_dict.get(LOG_HEADERS['transaction_id'],"bleep") == log_dict.get(LOG_HEADERS['transaction_id'],"bloop")):

                #         log_dict = {**log_dict, **tool_dict}
                #         tool_dict = {}

                # print("------JOINED DICT-------")
                # for key,val in log_dict.items():
                #     print(key, ":", val)
                # print("-------------------")
                

                # with open(output_file_path, 'a', newline='') as f: 
                #     csv_writer = csv.DictWriter(f, LOG_HEADERS.values(),delimiter="\t")
                #     csv_writer.writerow(log_dict)
    return ""

# def handle_session_start(msg):
#     pass

# def handle_context_message(msg):
#     pass

# def handle_tool_message(msg):
#     pass

# def handle_tutor_messages():
    # while True:
    #     session_id, msg = tutor_queue.get()

        



# def work_on_message_queue():

class PostItem(object):
    def __init__(self, xml_tree, session_id, priority):
        self.xml_tree = xml_tree
        self.session_id = session_id
        self.priority = priority

        
    def __eq__(self, other):
        return self.priority == other.priority

    def __ne__(self, other):
        return self.priority != other.priority

    def __lt__(self, other):
        return self.priority < other.priority

    def __le__(self, other):
        return self.priority <= other.priority

    def __gt__(self, other):
        return self.priority > other.priority

    def __ge__(self, other):
        return self.priority >= other.priority


def work_on_write_queue():
    while True:
        session_id,context_id = write_queue.get()
        # print("TYYPE", type(data))
        write_problem(session_id,context_id)
        write_queue.task_done()

def work_on_post_queue():
    while True:
        data = post_queue.get()
        # print("TYYPE", type(data))
        handle_post(data)
        post_queue.task_done()

for i in range(POST_THREADS):
    thread = threading.Thread(target=work_on_post_queue)
    thread.setDaemon(True)
    thread.start()

for i in range(WRITE_THREADS):
    thread = threading.Thread(target=work_on_write_queue)
    thread.setDaemon(True)
    thread.start()


def do_PRINT():
    _print_and_resp()
    return ""

def do_QUIT():
    _print_and_resp()
    shutdown_server()
    return 'Server shutting down...'

def do_GEN_NOOLS():
    post_data = request.get_data()
    d = json.loads(post_data)

    nools_dir = d['nools_dir']
    del d["nools_dir"]

    if not os.path.exists(nools_dir):
        try:
            os.makedirs(nools_dir)
        except OSError as exc: # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise

    print("---------------------------")
    print(json.dumps(d))
    print("---------------------------")

    generate_nools(d,nools_dir)
    with open(os.path.join(nools_dir, "rules.json"),'w') as f:
        json.dump(d,f)

    return ""


# counter = 0
# threadLock = threading.Lock()
def do_POST ():
    # global session_counter
    # global session_dicts
    # global counter
    # global threadLock

    # with threadLock:
    #     counter += 1
    # print("COUNT",counter)

    # return ""
    if(output_file_path == None):
        print("Received log message, but no output_file specifed.")
        return
    
    post_data = request.get_data()
    post_queue.put(post_data)




    # print(type(post_data))
    # handle_post(post_data)
    return ""

    

def do_GET():
    # print("GET")
    return app.send_static_file('index.html')


do_switch = {"PRINT":do_PRINT,
             "ERROR":do_PRINT,
             "QUIT": do_QUIT,
             "POST": do_POST,
             "GET" : do_GET}


@app.route('/<path:path>')
def static_proxy(path):
  # send_static_file will guess the correct MIME type
  # print("PROXY:", path)
  return app.send_static_file(path)

@app.route('/', methods=['QUIT','PRINT',"POST","GET"])
def handle_root():

    func = do_switch.get(request.method,None)
    # print("METHOD: %s" % request.method)
    if(func is not None):
        return func()
    else:
        return 400




# @app.route('/', methods=['PRINT'])
# def quit():
    
#     shutdown_server()
#     return 'Server shutting down...'



if __name__ == '__main__':
    # logging.basicConfig(level=logging.ERROR)

    assert len(sys.argv) > 1, "Error, correct usage: %s <port number>" % sys.argv[0]
    assert sys.argv[1].isdigit(), "invalid port %r" % sys.argv[1]
    port = int(sys.argv[1])
    if (len(sys.argv) > 2):
        output_file_path = sys.argv[2]

        # Make path if not exist
        if not os.path.exists(os.path.dirname(output_file_path)):
            try:
                os.makedirs(os.path.dirname(output_file_path))
            except OSError as exc: # Guard against race condition
                if exc.errno != errno.EEXIST:
                    raise


        with open(output_file_path, 'w', newline='') as f: 
            csv_writer = csv.DictWriter(f, LOG_HEADERS.values(),delimiter="\t")
            csv_writer.writeheader()

        log_file_handle = open(output_file_path, 'a', newline='') 
        csv_writer = csv.DictWriter(log_file_handle, LOG_HEADERS.values(),delimiter="\t")
    log = logging.getLogger('werkzeug')
    log.disabled = True

    app.run(HOST_DOMAIN,port,threaded=True)
   # print("IT DIED")