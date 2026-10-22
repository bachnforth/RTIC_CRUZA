import unittest
from unittest.mock import patch

import server
from test_fleet import heartbeat, packet


class DirectTelemetryTests(unittest.TestCase):
    def test_fragmented_and_combined_frames(self):
        raw = packet(heartbeat())
        frames, tail = server.split_frames(b'noise' + raw[:7])
        self.assertEqual(frames, [])
        frames, tail = server.split_frames(tail + raw[7:] + raw)
        self.assertEqual(frames, [raw, raw])
        self.assertEqual(tail, b'')

    def test_unsigned_v1_and_signed_v2_lengths(self):
        v1 = b'\xfe\x00' + bytes(6)
        signed = b'\xfd\x00\x01' + bytes(22)
        frames, tail = server.split_frames(v1 + signed[:-1])
        self.assertEqual(frames, [v1])
        frames, tail = server.split_frames(tail + signed[-1:])
        self.assertEqual(frames, [signed])
        self.assertEqual(tail, b'')

    def test_receives_aircraft_without_transmitting_and_closes_on_eof(self):
        class ReceiveOnlySocket:
            # No send/write methods: attempting an application transmission fails.
            closed = False
            chunks = iter([packet(heartbeat()), b''])

            def settimeout(self, value):
                pass

            def recv(self, size):
                return next(self.chunks)

            def close(self):
                self.closed = True

        class StopAfterConnection:
            stopped = False

            def is_set(self):
                return self.stopped

            def wait(self, timeout):
                self.stopped = True

        sock = ReceiveOnlySocket()
        source = server.DirectTelemetry('rn03', '100.100.0.6', 5760)
        with patch.object(server, 'STOP', StopAfterConnection()), \
                patch.object(server, 'telemetry_active', return_value=True), \
                patch.object(server.socket, 'create_connection', return_value=sock):
            source.run()
        self.assertTrue(source.snapshot()['online'])
        self.assertTrue(sock.closed)
        self.assertIsNone(source.sock)


if __name__ == '__main__':
    unittest.main()
