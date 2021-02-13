# Klippy WebHooks registration and server connection
#
# Copyright (C) 2020 Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license
import logging, socket, os, sys, errno, json
import gcode

# Json decodes strings as unicode types in Python 2.x.  This doesn't
# play well with some parts of Klipper (particuarly displays), so we
# need to create an object hook. This solution borrowed from:
#
# https://stackoverflow.com/questions/956867/
#
def byteify(data, ignore_dicts=False):
    if isinstance(data, unicode):
        return data.encode('utf-8')
    if isinstance(data, list):
        return [byteify(i, True) for i in data]
    if isinstance(data, dict) and not ignore_dicts:
        return {byteify(k, True): byteify(v, True)
                for k, v in data.items()}
    return data

class WebRequestError(gcode.CommandError):
    def __init__(self, message,):
        Exception.__init__(self, message)

    def to_dict(self):
        return {
            'error': 'WebRequestError',
            'message': str(self)}

class Sentinel:
    pass

class WebRequest:
    error = WebRequestError
    def __init__(self, client_conn, request):
        self.client_conn = client_conn
        base_request = json.loads(request)
        if type(base_request) != dict:
            raise ValueError("Not a top-level dictionary")
        self.id = base_request.get('id', None)
        self.method = base_request.get('method')
        self.params = base_request.get('params', {})
        if type(self.method) != str or type(self.params) != dict:
            raise ValueError("Invalid request type")
        self.response = None
        self.is_error = False

    def get_client_connection(self):
        return self.client_conn

    def get(self, item, default=Sentinel, types=None):
        value = self.params.get(item, default)
        if value is Sentinel:
            raise WebRequestError("Missing Argument [%s]" % (item,))
        if (types is not None and type(value) not in types
            and item in self.params):
            raise WebRequestError("Invalid Argument Type [%s]" % (item,))
        return value

    def get_str(self, item, default=Sentinel):
        return self.get(item, default, types=(str,))

    def get_int(self, item, default=Sentinel):
        return self.get(item, default, types=(int,))

    def get_float(self, item, default=Sentinel):
        return float(self.get(item, default, types=(int, float)))

    def get_dict(self, item, default=Sentinel):
        return self.get(item, default, types=(dict,))

    def get_method(self):
        return self.method

    def set_error(self, error):
        self.is_error = True
        self.response = error.to_dict()

    def send(self, data):
        if self.response is not None:
            raise WebRequestError("Multiple calls to send not allowed")
        self.response = data

    def finish(self):
        if self.id is None:
            return None
        rtype = "result"
        if self.is_error:
            rtype = "error"
        if self.response is None:
            # No error was set and the user never executed
            # send, default response is {}
            self.response = {}
        return {"id": self.id, rtype: self.response}

class ServerSocket:
    def __init__(self, webhooks, printer):
        self.printer = printer
        self.webhooks = webhooks
        self.reactor = printer.get_reactor()
        self.sock = self.fd_handle = None
        self.clients = {}
        start_args = printer.get_start_args()
        server_address = start_args.get('apiserver')
        is_fileinput = (start_args.get('debuginput') is not None)
        if not server_address or is_fileinput:
            # Do not enable server
            return
        self._remove_socket_file(server_address)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.setblocking(0)
        self.sock.bind(server_address)
        self.sock.listen(1)
        self.fd_handle = self.reactor.register_fd(
            self.sock.fileno(), self._handle_accept)
        printer.register_event_handler(
            'klippy:disconnect', self._handle_disconnect)

    def _handle_accept(self, eventtime):
        try:
            sock, addr = self.sock.accept()
        except socket.error:
            return
        sock.setblocking(0)
        client = ClientConnection(self, sock)
        self.clients[client.uid] = client

    def _handle_disconnect(self):
        for client in list(self.clients.values()):
            client.close()
        if self.sock is not None:
            self.reactor.unregister_fd(self.fd_handle)
            try:
                self.sock.close()
            except socket.error:
                pass

    def _remove_socket_file(self, file_path):
        try:
            os.remove(file_path)
        except OSError:
            if os.path.exists(file_path):
                logging.exception(
                    "webhooks: Unable to delete socket file '%s'"
                    % (file_path))
                raise

    def pop_client(self, client_id):
        self.clients.pop(client_id, None)

class ClientConnection:
    def __init__(self, server, sock):
        self.printer = server.printer
        self.webhooks = server.webhooks
        self.reactor = server.reactor
        self.server = server
        self.uid = id(self)
        self.sock = sock
        self.fd_handle = self.reactor.register_fd(
            self.sock.fileno(), self.process_received)
        self.partial_data = self.send_buffer = b""
        self.is_sending_data = False
        self.set_client_info("?", "New connection")

    def set_client_info(self, client_info, state_msg=None):
        if state_msg is None:
            state_msg = "Client info %s" % (repr(client_info),)
        logging.info("webhooks client %s: %s", self.uid, state_msg)
        log_id = "webhooks %s" % (self.uid,)
        if client_info is None:
            self.printer.set_rollover_info(log_id, None, log=False)
            return
        rollover_msg = "webhooks client %s: %s" % (self.uid, repr(client_info))
        self.printer.set_rollover_info(log_id, rollover_msg, log=False)

    def close(self):
        if self.fd_handle is None:
            return
        self.set_client_info(None, "Disconnected")
        self.reactor.unregister_fd(self.fd_handle)
        self.fd_handle = None
        try:
            self.sock.close()
        except socket.error:
            pass
        self.server.pop_client(self.uid)

    def is_closed(self):
        return self.fd_handle is None

    def process_received(self, eventtime):
        try:
            data = self.sock.recv(4096)
        except socket.error as e:
            # If bad file descriptor allow connection to be
            # closed by the data check
            if e.errno == errno.EBADF:
                data = b""
            else:
                return
        if not data:
            # Socket Closed
            self.close()
            return
        requests = data.split(b'\x03')
        requests[0] = self.partial_data + requests[0]
        self.partial_data = requests.pop()
        for req in requests:
            try:
                web_request = WebRequest(self, req)
            except Exception:
                logging.exception("webhooks: Error decoding Server Request %s"
                                  % (req))
                continue
            self.reactor.register_callback(
                lambda e, s=self, wr=web_request: s._process_request(wr))

    def _process_request(self, web_request):
        try:
            func = self.webhooks.get_callback(web_request.get_method())
            func(web_request)
        except self.printer.command_error as e:
            web_request.set_error(WebRequestError(str(e)))
        except Exception as e:
            msg = ("Internal Error on WebRequest: %s"
                   % (web_request.get_method()))
            logging.exception(msg)
            web_request.set_error(WebRequestError(str(e)))
            self.printer.invoke_shutdown(msg)
        result = web_request.finish()
        if result is None:
            return
        self.send(result)

    def send(self, data):
        self.send_buffer += json.dumps(data).encode() + b"\x03"
        if not self.is_sending_data:
            self.is_sending_data = True
            self.reactor.register_callback(self._do_send)

    def _do_send(self, eventtime):
        retries = 10
        while self.send_buffer:
            try:
                sent = self.sock.send(self.send_buffer)
            except socket.error as e:
                if e.errno == errno.EBADF or e.errno == errno.EPIPE \
                        or not retries:
                    sent = 0
                else:
                    retries -= 1
                    waketime = self.reactor.monotonic() + .001
                    self.reactor.pause(waketime)
                    continue
            retries = 10
            if sent > 0:
                self.send_buffer = self.send_buffer[sent:]
            else:
                logging.info(
                    "webhooks: Error sending server data,  closing socket")
                self.close()
                break
        self.is_sending_data = False

class WebHooks:
    def __init__(self, printer):
        self.printer = printer
        self._endpoints = {"list_endpoints": self._handle_list_endpoints}
        self._remote_methods = {}
        self.register_endpoint("info", self._handle_info_request)
        self.register_endpoint("emergency_stop", self._handle_estop_request)
        self.register_endpoint("register_remote_method",
                               self._handle_rpc_registration)
        self.sconn = ServerSocket(self, printer)

    def register_endpoint(self, path, callback):
        if path in self._endpoints:
            raise WebRequestError("Path already registered to an endpoint")
        self._endpoints[path] = callback

    def _handle_list_endpoints(self, web_request):
        web_request.send({'endpoints': list(self._endpoints.keys())})

    def _handle_info_request(self, web_request):
        client_info = web_request.get_dict('client_info', None)
        if client_info is not None:
            web_request.get_client_connection().set_client_info(client_info)
        state_message, state = self.printer.get_state_message()
        src_path = os.path.dirname(__file__)
        klipper_path = os.path.normpath(os.path.join(src_path, ".."))
        response = {'state': state, 'state_message': state_message,
                    'hostname': socket.gethostname(),
                    'klipper_path': klipper_path, 'python_path': sys.executable}
        start_args = self.printer.get_start_args()
        for sa in ['log_file', 'config_file', 'software_version', 'cpu_info']:
            response[sa] = start_args.get(sa)
        web_request.send(response)

    def _handle_estop_request(self, web_request):
        self.printer.invoke_shutdown("Shutdown due to webhooks request")

    def _handle_rpc_registration(self, web_request):
        template = web_request.get_dict('response_template')
        method = web_request.get_str('remote_method')
        new_conn = web_request.get_client_connection()
        logging.info("webhooks: registering remote method '%s' "
                     "for connection id: %d" % (method, id(new_conn)))
        self._remote_methods.setdefault(method, {})[new_conn] = template

    def get_connection(self):
        return self.sconn

    def get_callback(self, path):
        cb = self._endpoints.get(path, None)
        if cb is None:
            msg = "webhooks: No registered callback for path '%s'" % (path)
            logging.info(msg)
            raise WebRequestError(msg)
        return cb

    def get_status(self, eventtime):
        state_message, state = self.printer.get_state_message()
        return {'state': state, 'state_message': state_message}

    def call_remote_method(self, method, **kwargs):
        if method not in self._remote_methods:
            raise self.printer.command_error(
                "Remote method '%s' not registered" % (method))
        conn_map = self._remote_methods[method]
        valid_conns = {}
        for conn, template in conn_map.items():
            if not conn.is_closed():
                valid_conns[conn] = template
                out = {'params': kwargs}
                out.update(template)
                conn.send(out)
        if not valid_conns:
            del self._remote_methods[method]
            raise self.printer.command_error(
                "No active connections for method '%s'" % (method))
        self._remote_methods[method] = valid_conns

class GCodeHelper:
    def __init__(self, printer):
        self.printer = printer
        self.gcode = printer.lookup_object("gcode")
        # Output subscription tracking
        self.is_output_registered = False
        self.clients = {}
        # Register webhooks
        wh = printer.lookup_object('webhooks')
        wh.register_endpoint("gcode/help", self._handle_help)
        wh.register_endpoint("gcode/script", self._handle_script)
        wh.register_endpoint("gcode/restart", self._handle_restart)
        wh.register_endpoint("gcode/firmware_restart",
                             self._handle_firmware_restart)
        wh.register_endpoint("gcode/subscribe_output",
                             self._handle_subscribe_output)
    def _handle_help(self, web_request):
        web_request.send(self.gcode.get_command_help())
    def _handle_script(self, web_request):
        self.gcode.run_script(web_request.get_str('script'))
    def _handle_restart(self, web_request):
        self.gcode.run_script('restart')
    def _handle_firmware_restart(self, web_request):
        self.gcode.run_script('firmware_restart')
    def _output_callback(self, msg):
        for cconn, template in list(self.clients.items()):
            if cconn.is_closed():
                del self.clients[cconn]
                continue
            tmp = dict(template)
            tmp['params'] = {'response': msg}
            cconn.send(tmp)
    def _handle_subscribe_output(self, web_request):
        cconn = web_request.get_client_connection()
        template = web_request.get_dict('response_template', {})
        self.clients[cconn] = template
        if not self.is_output_registered:
            self.gcode.register_output_handler(self._output_callback)
            self.is_output_registered = True

SUBSCRIPTION_REFRESH_TIME = .25

class QueryStatusHelper:
    def __init__(self, printer):
        self.printer = printer
        self.clients = {}
        self.pending_queries = []
        self.query_timer = None
        self.last_query = {}
        # Register webhooks
        webhooks = printer.lookup_object('webhooks')
        webhooks.register_endpoint("objects/list", self._handle_list)
        webhooks.register_endpoint("objects/query", self._handle_query)
        webhooks.register_endpoint("objects/subscribe", self._handle_subscribe)
    def _handle_list(self, web_request):
        objects = [n for n, o in self.printer.lookup_objects()
                   if hasattr(o, 'get_status')]
        web_request.send({'objects': objects})
    def _do_query(self, eventtime):
        last_query = self.last_query
        query = self.last_query = {}
        msglist = self.pending_queries
        self.pending_queries = []
        msglist.extend(self.clients.values())
        # Generate get_status() info for each client
        for cconn, subscription, send_func, template in msglist:
            is_query = cconn is None
            if not is_query and cconn.is_closed():
                del self.clients[cconn]
                continue
            # Query each requested printer object
            cquery = {}
            for obj_name, req_items in subscription.items():
                res = query.get(obj_name, None)
                if res is None:
                    po = self.printer.lookup_object(obj_name, None)
                    if po is None or not hasattr(po, 'get_status'):
                        res = query[obj_name] = {}
                    else:
                        res = query[obj_name] = po.get_status(eventtime)
                if req_items is None:
                    req_items = list(res.keys())
                    if req_items:
                        subscription[obj_name] = req_items
                lres = last_query.get(obj_name, {})
                cres = {}
                for ri in req_items:
                    rd = res.get(ri, None)
                    if is_query or rd != lres.get(ri):
                        cres[ri] = rd
                if cres or is_query:
                    cquery[obj_name] = cres
            # Send data
            if cquery or is_query:
                tmp = dict(template)
                tmp['params'] = {'eventtime': eventtime, 'status': cquery}
                send_func(tmp)
        if not query:
            # Unregister timer if there are no longer any subscriptions
            reactor = self.printer.get_reactor()
            reactor.unregister_timer(self.query_timer)
            self.query_timer = None
            return reactor.NEVER
        return eventtime + SUBSCRIPTION_REFRESH_TIME
    def _handle_query(self, web_request, is_subscribe=False):
        objects = web_request.get_dict('objects')
        # Validate subscription format
        for k, v in objects.items():
            if type(k) != str or (v is not None and type(v) != list):
                raise web_request.error("Invalid argument")
            if v is not None:
                for ri in v:
                    if type(ri) != str:
                        raise web_request.error("Invalid argument")
        # Add to pending queries
        cconn = web_request.get_client_connection()
        template = web_request.get_dict('response_template', {})
        if is_subscribe and cconn in self.clients:
            del self.clients[cconn]
        reactor = self.printer.get_reactor()
        complete = reactor.completion()
        self.pending_queries.append((None, objects, complete.complete, {}))
        # Start timer if needed
        if self.query_timer is None:
            qt = reactor.register_timer(self._do_query, reactor.NOW)
            self.query_timer = qt
        # Wait for data to be queried
        msg = complete.wait()
        web_request.send(msg['params'])
        if is_subscribe:
            self.clients[cconn] = (cconn, objects, cconn.send, template)
    def _handle_subscribe(self, web_request):
        self._handle_query(web_request, is_subscribe=True)

def add_early_printer_objects(printer):
    printer.add_object('webhooks', WebHooks(printer))
    GCodeHelper(printer)
    QueryStatusHelper(printer)
