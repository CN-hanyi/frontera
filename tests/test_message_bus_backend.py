from __future__ import absolute_import
import unittest

from frontera.contrib.backends.remote.messagebus import MessageBusBackend
from frontera.settings import Settings
from frontera.core.models import Request, Response

data = {'id': 'xxx',
        'name': 'yyy'}

r1 = Request('http://www.example.com/',method='post',body=data, meta={b'domain': {b'fingerprint': b'1'}})
r2 = Request('http://www.scrapy.org/', meta={b'domain': {b'fingerprint': b'2'}})
r3 = Request('http://www.test.com/some/page', meta={b'domain': {b'fingerprint': b'3'}})


class TestMessageBusBackend(unittest.TestCase):

    def mbb_setup(self, settings=None):
        manager = type('manager', (object,), {})
        settings = settings or Settings()
        settings.MESSAGE_BUS = 'tests.mocks.message_bus.FakeMessageBus'
        settings.STORE_CONTENT = True
        #test json codecs
        # settings.MESSAGE_BUS_CODEC='frontera.contrib.backends.remote.codecs.json'
        manager.settings = settings
        manager.request_model = Request
        manager.response_model = Response
        return MessageBusBackend(manager)

    def test_feed_partitions_less_than_equal_partion_id_and_partion_id_less_than_zero(self):
        settings = Settings()
        # test partition_id > feed_partitions
        settings.SPIDER_PARTITION_ID = 2
        settings.SPIDER_FEED_PARTITIONS = 1
        self.assertRaises(ValueError, self.mbb_setup, settings)

        # test partition_id = feed_partitions
        settings.SPIDER_PARTITION_ID = 1
        self.assertRaises(ValueError, self.mbb_setup, settings)

        # test partition_id < 0
        settings.SPIDER_PARTITION_ID = -1
        self.assertRaises(ValueError, self.mbb_setup, settings)

    def test_add_seeds(self):
        mbb = self.mbb_setup()
        mbb.add_seeds([r1, r2, r3])
        seeds = [mbb._decoder.decode(m)[1][0] for m in mbb.spider_log_producer.messages]
        self.assertEqual(set([seed.url for seed in seeds]), set([r1.url, r2.url, r3.url]))
        seed=seeds[0]
        self.assertEqual(b'POST',seed.method)
        self.assertEqual(data,seed.body)

    def test_page_crawled(self):
        mbb = self.mbb_setup()
        resp = Response(r1.url, body=b'body', request=r1)
        mbb.page_crawled(resp)
        page = mbb._decoder.decode(mbb.spider_log_producer.messages[0])[1]
        self.assertEqual((page.request.url, page.body), (resp.request.url, b'body'))

    def test_links_extracted(self):
        mbb = self.mbb_setup()
        mbb.links_extracted(r1, [r2, r3])
        requests = [mbb._decoder.decode(m)[1] for m in mbb.spider_log_producer.messages]
        links = [mbb._decoder.decode(m)[2][0] for m in mbb.spider_log_producer.messages]
        self.assertEqual(set([r.url for r in requests]), set([r1.url]))
        self.assertEqual(b'POST', requests[0].method)
        self.assertEqual(data, requests[0].body)
        self.assertEqual(set([link.url for link in links]), set([r2.url, r3.url]))

    def test_request_error(self):
        mbb = self.mbb_setup()
        mbb.request_error(r1, 'error')
        _, error_request, error_message = mbb._decoder.decode(mbb.spider_log_producer.messages[0])
        self.assertEqual((error_request.url, error_message), (r1.url, 'error'))
        self.assertEqual(b'POST', error_request.method)
        self.assertEqual(data, error_request.body)

    def test_get_next_requests(self):
        mbb = self.mbb_setup()
        encoded_requests = [mbb._encoder.encode_request(r) for r in [r1, r2, r3]]
        mbb.consumer.put_messages(encoded_requests)
        mbb.consumer._set_offset(0)
        requests = set(mbb.get_next_requests(10, overused_keys=[], key_type='domain'))
        _, partition_id, offset = mbb._decoder.decode(mbb.spider_log_producer.messages[0])
        self.assertEqual((partition_id, offset), (0, 0))
        self.assertEqual(set([r.url for r in requests]), set([r1.url, r2.url, r3.url]))
        requests = set(mbb.get_next_requests(10, overused_keys=[], key_type='domain'))
        self.assertEqual([r.url for r in requests], [])
        # test overused keys
        mbb.consumer.put_messages(encoded_requests)
        requests = set(mbb.get_next_requests(10, overused_keys=['www.example.com'], key_type='domain'))
        self.assertEqual(set([r.url for r in requests]), set([r2.url, r3.url]))
        #test get post request
        requests = mbb.get_next_requests(10, overused_keys=[], key_type='domain')
        self.assertEqual(b'POST', requests[0].method)
        self.assertEqual(data, requests[0].body)
