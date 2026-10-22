import importlib.util
from pathlib import Path
import socket
import threading
import unittest

spec = importlib.util.spec_from_file_location('mesh_relay', Path(__file__).with_name('mesh-relay.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RelayTest(unittest.TestCase):
    def test_reply_is_delivered_to_correct_client_and_other_sources_are_rejected(self):
        target = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        target.bind(('127.0.0.1', 0))
        target.settimeout(2)
        relay = module.Relay(dict(vpn_bind_ip='127.0.0.1', mesh_source_ip='127.0.0.1',
                                 allowed_sources=['127.0.0.1'], mappings=[dict(
                                     listen_port=0, destination_ip='127.0.0.1',
                                     destination_port=target.getsockname()[1])]))
        address = relay.listeners[0].getsockname()
        stopped = threading.Event()

        def serve():
            while not stopped.is_set():
                relay.tick(0.01)

        worker = threading.Thread(target=serve)
        worker.start()
        clients = []
        try:
            for payload in (b'first', b'second'):
                client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                clients.append(client)
                client.bind(('127.0.0.1', 0))
                client.settimeout(2)
                client.sendto(payload, address)
            received = [target.recvfrom(4096) for _ in range(2)]
            self.assertEqual({x[0] for x in received}, {b'first', b'second'})
            for packet, origin in reversed(received):
                target.sendto(b'answer:' + packet, origin)
            self.assertEqual(clients[0].recvfrom(4096)[0], b'answer:first')
            self.assertEqual(clients[1].recvfrom(4096)[0], b'answer:second')
            attacker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            clients.append(attacker)
            attacker.bind(('127.0.0.2', 0))
            attacker.sendto(b'blocked', address)
            target.settimeout(0.2)
            with self.assertRaises(socket.timeout):
                target.recvfrom(4096)
            self.assertEqual(relay.counts['rejected'], 1)
        finally:
            stopped.set()
            worker.join(2)
            relay.close()
            target.close()
            for client in clients:
                client.close()


if __name__ == '__main__':
    unittest.main()
