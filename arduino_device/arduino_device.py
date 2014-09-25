from __future__ import print_function, division
import serial
import time
import atexit
import json
import functools
import operator
import platform

from serial_device import SerialDevice, SerialDevices, find_serial_device_ports, WriteFrequencyError


DEBUG = False
BAUDRATE = 9600

class ArduinoDevice(SerialDevice):

    TIMEOUT = 0.05
    WRITE_WRITE_DELAY = 0.05
    RESET_DELAY = 2.0
    CMD_GET_DEVICE_INFO = 0
    CMD_GET_CMDS = 1
    CMD_GET_RSP_CODES = 2

    def __init__(self,*args,**kwargs):
        model_number = None
        serial_number = None
        if 'debug' not in kwargs:
            kwargs.update({'debug': DEBUG})
        if 'try_ports' in kwargs:
            try_ports = kwargs.pop('try_ports')
        else:
            try_ports = None
        if 'baudrate' not in kwargs:
            kwargs.update({'baudrate': BAUDRATE})
        elif (kwargs['baudrate'] is None) or (str(kwargs['baudrate']).lower() == 'default'):
            kwargs.update({'baudrate': BAUDRATE})
        if 'timeout' not in kwargs:
            kwargs.update({'timeout': self.TIMEOUT})
        if 'write_write_delay' not in kwargs:
            kwargs.update({'write_write_delay': self.WRITE_WRITE_DELAY})
        if 'model_number' in kwargs:
            model_number = kwargs.pop('model_number')
        if 'serial_number' in kwargs:
            serial_number = kwargs.pop('serial_number')
        if ('port' not in kwargs) or (kwargs['port'] is None):
            port =  find_arduino_device_port(baudrate=kwargs['baudrate'],
                                             model_number=model_number,
                                             serial_number=serial_number,
                                             try_ports=try_ports,
                                             debug=kwargs['debug'])
            kwargs.update({'port': port})

        t_start = time.time()
        super(ArduinoDevice,self).__init__(*args,**kwargs)
        atexit.register(self._exit_arduino_device)
        time.sleep(self.RESET_DELAY)
        self.rsp_dict = None
        self.rsp_dict = self._get_rsp_dict()
        self.cmd_dict = self._get_cmd_dict()
        self.cmd_dict_inv = dict([(v,k) for (k,v) in self.cmd_dict.iteritems()])
        self._create_cmds()
        dev_info = self.getDevInfo()
        self.model_number = dev_info['model_number']
        self.serial_number = dev_info['serial_number']
        self.firmware_number = dev_info['firmware_number']
        t_end = time.time()
        self.debug_print('Initialization time =', (t_end - t_start))

    def _exit_arduino_device(self):
        pass

    def _args_to_cmd_str(self,*args):
        cmd_list = ['[', ','.join(map(str,args)), ']']
        cmd_str = ''.join(cmd_list)
        return cmd_str

    def _send_cmd(self,*args):

        '''Sends Arduino command to device over serial port and
        returns number of bytes written'''

        cmd_str = self._args_to_cmd_str(*args)
        self.debug_print('cmd_str', cmd_str)
        bytes_written = self.write_check_freq(cmd_str,delay_write=True)
        return bytes_written

    def _send_cmd_get_rsp(self,*args):

        '''Sends Arduino command to device over serial port and
        returns response'''

        cmd_str = self._args_to_cmd_str(*args)
        self.debug_print('cmd_str', cmd_str)
        rsp_str = self.write_read(cmd_str,use_readline=True,check_write_freq=True)
        if rsp_str is None:
            rsp_dict = {}
            return rsp_dict
        self.debug_print('rsp_str', rsp_str)
        try:
            rsp_dict = json_str_to_dict(rsp_str)
        except Exception, e:
            err_msg = 'Unable to parse device response {0}.'.format(str(e))
            raise IOError, err_msg
        try:
            status = rsp_dict.pop('status')
        except KeyError:
            err_msg = 'Device response does not contain status.'
            raise IOError, err_msg
        try:
            rsp_cmd_id  = rsp_dict.pop('cmd_id')
        except KeyError:
            err_msg = 'Device response does not contain cmd_id.'
            raise IOError, err_msg
        if not rsp_cmd_id == args[0]:
            raise IOError, 'Device response cmd_id does not match that sent.'
        if self.rsp_dict is not None:
            if status == self.rsp_dict['rsp_error']:
                try:
                    dev_err_msg = '(from device) {0}'.format(rsp_dict['err_msg'])
                except KeyError:
                    dev_err_msg = "Error message missing."
                err_msg = '{0}'.format(dev_err_msg)
                raise IOError, err_msg
        return rsp_dict

    def get_arduino_serial_number(self):
        dev_info = self.getDevInfo()
        self.serial_number = dev_info['serial_number']
        return self.serial_number

    def get_arduino_model_number(self):
        dev_info = self.getDevInfo()
        self.model_number = dev_info['model_number']
        return self.model_number

    def get_arduino_firmware_number(self):
        dev_info = self.getDevInfo()
        self.firmware_number = dev_info['firmware_number']
        return self.firmware_number

    def get_arduino_device_info(self):
        arduino_device_info = self.get_serial_device_info()
        dev_info = self.getDevInfo()
        self.model_number = dev_info['model_number']
        self.serial_number = dev_info['serial_number']
        self.firmware_number = dev_info['firmware_number']
        arduino_device_info.update({'model_number': self.model_number,
                                    'serial_number': self.serial_number,
                                    'firmware_number': self.firmware_number,
                                    })
        return arduino_device_info

    def _get_cmd_dict(self):
        cmd_dict = self._send_cmd_get_rsp(self.CMD_GET_CMDS)
        return cmd_dict

    def get_arduino_commands(self):
        return self.cmd_dict.keys()

    def _get_rsp_dict(self):
        rsp_dict = self._send_cmd_get_rsp(self.CMD_GET_RSP_CODES)
        check_dict_for_key(rsp_dict,'rsp_success',dname='rsp_dict')
        check_dict_for_key(rsp_dict,'rsp_error',dname='rsp_dict')
        return rsp_dict

    def _send_cmd_by_name(self,name,*args):
        cmd_id = self.cmd_dict[name]
        cmd_args = [cmd_id]
        cmd_args.extend(args)
        rsp = self._send_cmd_get_rsp(*cmd_args)
        return rsp

    def _send_all_cmds(self):
        print('\nSend All Commands')
        print('-------------------')
        for cmd_id, cmd_name in sorted(self.cmd_dict_inv.iteritems()):
            print('cmd: {0}, {1}'.format(cmd_name,cmd_id))
            rsp = self._send_cmd_get_rsp(cmd_id)
            print('rsp: {0}'.format(rsp))
            print()
        print()

    def _cmd_func_base(self,cmd_name,*args):
        if len(args) == 1 and type(args[0]) is dict:
            args_dict = args[0]
            args_list = self._args_dict_to_list(args_dict)
        else:
            args_list = args
        rsp_dict = self._send_cmd_by_name(cmd_name,*args_list)
        if rsp_dict:
            ret_value = self._process_rsp_dict(rsp_dict)
            return ret_value

    def _create_cmds(self):
        self.cmd_func_dict = {}
        for cmd_id, cmd_name in sorted(self.cmd_dict_inv.items()):
            cmd_func = functools.partial(self._cmd_func_base, cmd_name)
            setattr(self,cmd_name,cmd_func)
            self.cmd_func_dict[cmd_name] = cmd_func

    def _process_rsp_dict(self,rsp_dict):
        if len(rsp_dict) == 1:
            ret_value = rsp_dict.values()[0]
        else:
            all_values_empty = True
            for v in rsp_dict.values():
                if not type(v) == str or v:
                    all_values_empty = False
                    break
            if all_values_empty:
                ret_value = sorted(rsp_dict.keys())
            else:
                ret_value = rsp_dict
        return ret_value

    def _args_dict_to_list(self,args_dict):
        key_set = set(args_dict.keys())
        order_list = sorted([(num,name) for (name,num) in order_dict.iteritems()])
        args_list = [args_dict[name] for (num, name) in order_list]
        return args_list

# device_names example:
# [{'port':'/dev/ttyACM0',
#   'device_name':'arduino0'},
#  {'model_number':232,
#   'serial_number':3,
#   'device_name':'arduino1'}]
class ArduinoDevices(SerialDevices):

    def __init__(self,*args,**kwargs):
        if ('use_ports' not in kwargs) or (kwargs['use_ports'] is None):
            kwargs['use_ports'] = find_arduino_device_ports(*args,**kwargs)
            sort = True
        else:
            sort = False
        super(ArduinoDevices,self).__init__(*args,**kwargs)
        if sort:
            self.sort_by_model_number()

    def append_device(self,*args,**kwargs):
        self.append(ArduinoDevice(*args,**kwargs))

    def get_arduino_devices_info(self):
        arduino_devices_info = []
        for dev in self:
            arduino_devices_info.append(dev.get_arduino_device_info())
        return arduino_devices_info

    def sort_by_model_number(self,*args,**kwargs):
        kwargs['key'] = operator.attrgetter('model_number','serial_number','device_name','port')
        self.sort(**kwargs)

    def get_by_model_number(self,model_number):
        dev_list = []
        for device_index in range(len(self)):
            dev = self[device_index]
            if dev.model_number == model_number:
                dev_list.append(dev)
        if len(dev_list) == 1:
            return dev_list[0]
        elif 1 < len(dev_list):
            return dev_list

    def sort_by_serial_number(self,*args,**kwargs):
        self.sort_by_model_number(*args,**kwargs)

    def get_by_serial_number(self,serial_number):
        dev_list = []
        for device_index in range(len(self)):
            dev = self[device_index]
            if dev.serial_number == serial_number:
                dev_list.append(dev)
        if len(dev_list) == 1:
            return dev_list[0]
        elif 1 < len(dev_list):
            return dev_list


def check_dict_for_key(d,k,dname=''):
    if not k in d:
        if not dname:
            dname = 'dictionary'
        raise IOError, '{0} does not contain {1}'.format(dname,k)

def json_str_to_dict(json_str):
    json_dict =  json.loads(json_str,object_hook=json_decode_dict)
    return json_dict

def json_decode_dict(data):
    """
    Object hook for decoding dictionaries from serialized json data. Ensures that
    all strings are unpacked as str objects rather than unicode.
    """
    rv = {}
    for key, value in data.iteritems():
        if isinstance(key, unicode):
            key = key.encode('utf-8')
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        elif isinstance(value, list):
            value = json_decode_list(value)
        elif isinstance(value, dict):
            value = json_decode_dict(value)
        rv[key] = value
    return rv

def json_decode_list(data):
    """
    Object hook for decoding lists from serialized json data. Ensures that
    all strings are unpacked as str objects rather than unicode.
    """
    rv = []
    for item in data:
        if isinstance(item, unicode):
            item = item.encode('utf-8')
        elif isinstance(item, list):
            item = json_decode_list(item)
        elif isinstance(item, dict):
            item = json_decode_dict(item)
        rv.append(item)
    return rv

def find_arduino_device_ports(baudrate=None, model_number=None, serial_number=None, try_ports=None, debug=DEBUG):
    serial_device_ports = find_serial_device_ports(try_ports=try_ports, debug=debug)
    os_type = platform.system()
    if os_type == 'Darwin':
        serial_device_ports = [x for x in serial_device_ports if 'tty.usbmodem' in x or 'tty.usbserial' in x]

    if type(model_number) is int:
        model_number = [model_number]
    if type(serial_number) is int:
        serial_number = [serial_number]

    arduino_device_ports = {}
    for port in serial_device_ports:
        try:
            dev = ArduinoDevice(port=port,baudrate=baudrate)
            try:
                dev_info = dev.getDevInfo()
                if DEBUG:
                    print("dev_info = " + str(dev_info))
            except Exception:
                break
            try:
                dev_model_number = dev_info['model_number']
            except KeyError:
                break
            if (model_number is None ) or (dev_model_number in model_number):
                try:
                    dev_serial_number = dev_info['serial_number']
                except KeyError:
                    break
                if (serial_number is None) or (dev_serial_number in serial_number):
                    arduino_device_ports[port] = {'model_number': dev_model_number,
                                                  'serial_number': dev_serial_number}
            dev.close()
        except (serial.SerialException, IOError):
            pass
    return arduino_device_ports

def find_arduino_device_port(baudrate=None, model_number=None, serial_number=None, try_ports=None, debug=DEBUG):
    arduino_device_ports = find_arduino_device_ports(baudrate=baudrate,
                                                     model_number=model_number,
                                                     serial_number=serial_number,
                                                     try_ports=try_ports,
                                                     debug=debug)
    if len(arduino_device_ports) == 1:
        return arduino_device_ports.keys()[0]
    elif len(arduino_device_ports) == 0:
        serial_device_ports = find_serial_device_ports(try_ports)
        err_str = 'Could not find any Arduino devices. Check connections and permissions.\n'
        err_str += 'Tried ports: ' + str(serial_device_ports)
        raise RuntimeError(err_str)
    else:
        err_str = 'Found more than one Arduino device. Specify port or model_number and/or serial_number.\n'
        err_str += 'Matching ports: ' + str(arduino_device_ports)
        raise RuntimeError(err_str)


# -----------------------------------------------------------------------------------------
if __name__ == '__main__':

    debug = False
    dev = ArduinoDevice(debug=debug)
