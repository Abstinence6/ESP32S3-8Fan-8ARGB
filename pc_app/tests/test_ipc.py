"""No pyserial/Qt dependency: localhost framing and single-owner behaviour."""
import socket
import unittest

from pc_app.ipc import AgentSerialBridge, AgentSerialProxy, READY, _frame


class PhysicalPort:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)


class AgentIpcTests(unittest.TestCase):
    def test_frame_roundtrip_and_reject_oversize(self):
        self.assertEqual(_frame(b"W", b"abc"), b"W\x00\x03abc")
        with self.assertRaises(ValueError):
            _frame(b"W", b"a" * 8193)
        with self.assertRaises(ValueError):
            _frame(b"B", b"x")

    def test_agent_is_only_usb_owner(self):
        bridge = AgentSerialBridge(port=0)
        bridge.start()
        # Use actual ephemeral server port instead of fixed port in CI.
        port = bridge._server.getsockname()[1]
        physical = PhysicalPort()
        client = socket.create_connection(("127.0.0.1", port), timeout=1)
        try:
            bridge.poll(physical)
            self.assertEqual(client.recv(len(READY)), READY)
            proxy = AgentSerialProxy(client)
            self.assertEqual(proxy.write(b"FAN 1 100\n"), 10)
            bridge.poll(physical)
            self.assertEqual(physical.writes, [b"FAN 1 100\n"])
            bridge.forward_rx(b"CH 1 FAN=100%\n")
            self.assertEqual(proxy.read(proxy.in_waiting), b"CH 1 FAN=100%\n")
            proxy.close()
            bridge.poll(physical)
        finally:
            bridge.close()

    def test_agent_refuses_without_physical_device(self):
        bridge = AgentSerialBridge(port=0)
        bridge.start()
        port = bridge._server.getsockname()[1]
        client = socket.create_connection(("127.0.0.1", port), timeout=1)
        try:
            bridge.poll(None)
            self.assertEqual(client.recv(1), b"")
        finally:
            client.close()
            bridge.close()


if __name__ == "__main__":
    unittest.main()
