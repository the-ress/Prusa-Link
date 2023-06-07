"""A module implementing the IPC queue message consumer"""
import logging
import os
import queue
from threading import Thread
from typing import Callable

from ipcqueue import posixmq  # type: ignore

from ..const import QUIT_INTERVAL
from ..util import prctl_name

log = logging.getLogger(__name__)


class IPCConsumer:
    """Class that sets up and consumes a message queue"""

    @staticmethod
    def get_queue_path(queue_name):
        """Returns the path to a message queue with the given name"""
        # os path join needs the queue name without the leading slash
        if queue_name.startswith("/"):
            queue_name = queue_name[1:]
        return os.path.join("/dev/mqueue", queue_name)

    def __init__(self,
                 queue_name,
                 chown_uid=None,
                 chown_gid=None):
        if not queue_name.startswith("/"):
            raise ValueError("Queue name must start with a slash")

        self.queue_name = queue_name
        self.queue_path = self.get_queue_path(queue_name)
        self.chown_uid = chown_uid if chown_uid is not None else os.getuid()
        self.chown_gid = chown_gid if chown_gid is not None else os.getgid()

        self.running = False
        self.ipc_queue = None
        self.command_handlers = {}

        self.ipc_queue_thread = Thread(
            target=self._read_commands, name="mi_cmd_reader")

    def add_handler(self, command: str, handler: Callable[[], None]):
        """Adds a handler for a text command"""
        # TODO: add support for args and kwargs
        self.command_handlers[command] = handler

    def start(self):
        """Starts the message queue consumer"""
        self.running = True
        self._setup_queue()
        self.ipc_queue_thread.start()

    def stop(self):
        """Stops the consumer"""
        self.running = False
        self.ipc_queue_thread.join()
        self.ipc_queue.unlink()

    def _setup_queue(self):
        """Creates the pipe and sets the correct permissions"""
        if os.path.exists(self.queue_path):
            os.remove(self.queue_path)
            # If this fails, we should exit, the queue
            # could contain malicious messages

        self.ipc_queue = posixmq.Queue(self.queue_name)

        os.chown(self.queue_path,
                 uid=self.chown_uid,
                 gid=self.chown_gid)

    def _read_commands(self):
        """Reads commands from the pipe and executes their handlers"""
        # pylint: disable=deprecated-method
        prctl_name()

        while self.running:
            try:
                command = self.ipc_queue.get(block=True, timeout=QUIT_INTERVAL)
            except queue.Empty:
                continue

            log.debug("read: '%s' from ipc queue", command)
            try:
                if command in self.command_handlers:
                    self.command_handlers[command]()
                else:
                    log.debug("Unknown command for multi instance '%s'",
                              command)
            except Exception:  # pylint: disable=broad-except
                log.exception("Exception occurred while handling an IPC"
                              " command")
