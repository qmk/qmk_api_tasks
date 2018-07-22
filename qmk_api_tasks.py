#!/usr/bin/env python3
import random
import threading
from os import environ
from time import sleep, strftime
from traceback import print_exc
from wsgiref.simple_server import make_server

environ['S3_ACCESS_KEY'] = environ.get('S3_ACCESS_KEY', 'minio_dev')
environ['S3_SECRET_KEY'] = environ.get('S3_SECRET_KEY', 'minio_dev_secret')

import qmk_redis
from qmk_compiler import compile_firmware


# Simple WSGI app to give Rancher a healthcheck to hit
port = 5000
status = {
    'good': ['200 OK', '¡Bueno!\n'],
    'bad': ['500 Internal Server Error', '¡Muy mal!\n'],
    'current': 'bad'
}


def current_status(i):
    """Return the current status.
    """
    return status[status['current']][i]


def wsgi_app(environ, start_response):
    start_response(current_status(0), [('Content-Type', 'text/plain')])
    return [current_status(1).encode('UTF-8')]


class WebThread(threading.Thread):
    def run(self):
        httpd = make_server('', port, wsgi_app)
        httpd.serve_forever()


# The main part of the app, iterate over all keyboards and build them.
class TaskThread(threading.Thread):
    def run(self):
        status['current'] = 'good'
        keyboards_tested = qmk_redis.get('qmk_api_keyboards_tested')
        if not keyboards_tested:
            keyboards_tested = {}

        failed_keyboards = qmk_redis.get('qmk_api_keyboards_failed')
        if not failed_keyboards:
            failed_keyboards = {}

        while True:
            try:
                for keyboard in qmk_redis.get('qmk_api_keyboards'):
                    metadata = qmk_redis.get('qmk_api_kb_%s' % (keyboard))
                    if not metadata['layouts']:
                        keyboards_tested[keyboard + '/[NO_LAYOUTS]'] = False
                        failed_keyboards[keyboard + '/[NO_LAYOUTS]'] = {'severity': 'error', 'message': 'QMK Configurator Support Broken:\n\nNo layouts defined.'}
                        continue

                    layout_macro = random.choice(list(metadata['layouts']))  # Pick a LAYOUT macro at random
                    keyboard_layout_name = '/'.join((keyboard,layout_macro))
                    layout = list(map(lambda x:'KC_NO', metadata['layouts'][layout_macro]['layout']))
                    layers = [layout, list(map(lambda x:'KC_TRNS', layout))]

                    # Enqueue the job
                    print('***', strftime('%Y-%m-%d %H:%M:%S'))
                    print('Beginning test compile for %s, layout %s' % (keyboard, layout_macro))
                    job = compile_firmware.delay(keyboard, 'qmk_api_tasks_test_compile', layout_macro, layers)
                    print('Successfully enqueued, polling every 2 seconds...')
                    while not job.result:
                        sleep(2)

                    # Check over the job results
                    if job.result['returncode'] == 0:
                        print('Compile job completed successfully!')
                        keyboards_tested[keyboard_layout_name] = True
                        if keyboard_layout_name in failed_keyboards:
                            del(failed_keyboards[keyboard_layout_name])
                    else:
                        print('Could not compile %s, layout %s' % (keyboard, layout_macro))
                        print(job.result['output'])
                        keyboards_tested[keyboard_layout_name] = False
                        failed_keyboards[keyboard_layout_name] = {'severity': 'error', 'message': 'QMK Configurator Support Broken:\n\n%s' % job.result['output']}

                    # Write our current progress to redis
                    print('\n\n\n\n')
                    qmk_redis.set('qmk_api_keyboards_tested', keyboards_tested)
                    qmk_redis.set('qmk_api_keyboards_failed', failed_keyboards)

            except Exception as e:
                print('***', strftime('%Y-%m-%d %H:%M:%S'))
                print('Uncaught exception!', e.__class__.__name__)
                print(e)
                print_exc()

        print('How did we get here this should be impossible! HELP! HELP! HELP!')
        status['current'] = 'bad'



if __name__ == '__main__':
    w = WebThread()
    t = TaskThread()
    w.start()
    t.start()
