"""/api/printer endpoint handlers"""
from poorwsgi import state
from poorwsgi.response import JSONResponse
from prusa.connect.printer.const import State

from .lib.core import app
from .lib.auth import check_api_digest

from ..printer_adapter.input_output.serial.helpers import enqueue_instruction
from ..printer_adapter.const import SPEED, FEEDRATE, MAX_FEEDRATE_E, FLOWRATE,\
    COORDINATES, MIN_EXTRUSION_TEMP


def jog(req, serial_queue):
    """XYZ movement command"""
    # pylint: disable=too-many-branches
    absolute = req.json.get('absolute')
    feedrate = req.json.get('feedrate')

    # Compatibility with OctoPrint, OP speed == Prusa feedrate in mm/min
    if not feedrate:
        feedrate = req.json.get('speed')

    axes = []

    if not feedrate or \
            feedrate < FEEDRATE['MIN'] or feedrate > FEEDRATE['MAX']:
        feedrate = FEEDRATE['MIN']

    # --- Coordinates ---
    x_axis = req.json.get('x')
    y_axis = req.json.get('y')
    z_axis = req.json.get('z')

    if x_axis is not None:
        if absolute:
            if x_axis < COORDINATES['MIN']:
                x_axis = COORDINATES['MIN']
            elif x_axis > COORDINATES['MAX_X']:
                x_axis = COORDINATES['MAX_X']
        axes.append(f'X{x_axis}')

    if y_axis is not None:
        if absolute:
            if y_axis < COORDINATES['MIN']:
                y_axis = COORDINATES['MIN']
            elif y_axis > COORDINATES['MAX_Y']:
                y_axis = COORDINATES['MAX_Y']
        axes.append(f'Y{y_axis}')

    if z_axis is not None:
        if absolute:
            if z_axis < COORDINATES['MIN']:
                z_axis = COORDINATES['MIN']
            elif z_axis > COORDINATES['MAX_Z']:
                z_axis = COORDINATES['MAX_Z']
        axes.append(f'Z{z_axis}')

    if absolute:
        # G90 - absolute movement
        enqueue_instruction(serial_queue, 'G90')
    else:
        # G91 - relative movement
        enqueue_instruction(serial_queue, 'G91')

    # G1 - linear movement in given axes
    gcode = f'G1 F{feedrate} {axes}'
    enqueue_instruction(serial_queue, gcode)


def home(req, serial_queue):
    """XYZ homing command"""
    axes = req.json.get('axes')
    if not axes:
        axes = ['X', 'Y', 'Z']
    gcode = f'G28 {axes}'
    enqueue_instruction(serial_queue, gcode)


def set_speed(req, serial_queue):
    """Speed set command"""
    factor = req.json.get('factor')
    if not factor:
        factor = 100
    elif factor < SPEED['MIN']:
        factor = SPEED['MIN']
    elif factor > SPEED['MAX']:
        factor = SPEED['MAX']

    gcode = f'M220 S{factor}'
    enqueue_instruction(serial_queue, gcode)


def set_target_temperature(req, serial_queue):
    """Target temperature set command"""
    targets = req.json.get('targets')

    # Compability with OctoPrint, which uses more tools, here only tool0
    tool = targets['tool0']

    gcode = f'M104 S{tool}'
    enqueue_instruction(serial_queue, gcode)


def extrude(req, serial_queue):
    """Extrude given amount of filament in mm, negative value will retract"""
    amount = req.json.get('amount')
    feedrate = req.json.get('feedrate')

    # Compatibility with OctoPrint, OP speed == Prusa feedrate in mm/min
    if not feedrate:
        # If feedrate is not defined, use maximum value for E axis
        feedrate = req.json.get('speed', MAX_FEEDRATE_E)

    # M83 - relative movement for axis E
    enqueue_instruction(serial_queue, 'M83')

    gcode = f'G1 F{feedrate} E{amount}'
    enqueue_instruction(serial_queue, gcode)


def set_flowrate(req, serial_queue):
    """Set flow rate factor to apply to extrusion of the tool"""
    factor = req.json.get('factor')
    if factor < FLOWRATE['MIN']:
        factor = FLOWRATE['MIN']
    elif factor > FLOWRATE['MAX']:
        factor = FLOWRATE['MAX']

    gcode = f'M221 S{factor}'
    enqueue_instruction(serial_queue, gcode)


@app.route('/api/printer/printhead', method=state.METHOD_POST)
@check_api_digest
def api_printhead(req):
    """Control the printhead movement in XYZ axes"""
    serial_queue = app.daemon.prusa_link.serial_queue
    printer_state = app.daemon.prusa_link.model.last_telemetry.state
    operational = printer_state in (State.READY, State.FINISHED, State.STOPPED)
    command = req.json.get('command')
    status = state.HTTP_NO_CONTENT

    if command == 'jog':
        if operational:
            jog(req, serial_queue)
        else:
            status = state.HTTP_CONFLICT

    elif command == 'home':
        if operational:
            home(req, serial_queue)
        else:
            status = state.HTTP_CONFLICT

    elif command == 'speed':
        set_speed(req, serial_queue)

    # Compatibility with OctoPrint, OP feedrate == Prusa speed in %
    elif command == 'feedrate':
        set_speed(req, serial_queue)

    return JSONResponse(status_code=status)


@app.route('/api/printer/tool', method=state.METHOD_POST)
@check_api_digest
def api_tool(req):
    """Control the extruder, including E axis"""
    serial_queue = app.daemon.prusa_link.serial_queue
    tel = app.daemon.prusa_link.model.last_telemetry
    command = req.json.get('command')
    status = state.HTTP_NO_CONTENT

    if command == 'target':
        set_target_temperature(req, serial_queue)

    elif command == 'extrude':
        if tel.state is not State.PRINTING and \
                tel.temp_nozzle >= MIN_EXTRUSION_TEMP:
            extrude(req, serial_queue)
        else:
            status = state.HTTP_CONFLICT

    elif command == 'flowrate':
        set_flowrate(req, serial_queue)

    return JSONResponse(status_code=status)
