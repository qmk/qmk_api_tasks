#!/usr/bin/env python3
import threading
from os import environ
from time import sleep, strftime, time
from traceback import print_exc
from wsgiref.simple_server import make_server, WSGIRequestHandler

environ['S3_ACCESS_KEY'] = environ.get('S3_ACCESS_KEY', 'minio_dev')
environ['S3_SECRET_KEY'] = environ.get('S3_SECRET_KEY', 'minio_dev_secret')
COMPILE_TIMEOUT = int(environ.get('COMPILE_TIMEOUT', 300))                # 5 minutes, how long we wait for a specific board to compile
S3_CLEANUP_TIMEOUT = int(environ.get('S3_CLEANUP_TIMEOUT', 7200))         # 2 Hours, how long we wait for the S3 cleanup process to run
BUILD_STATUS_TIMEOUT = int(environ.get('BUILD_STATUS_TIMEOUT', 86400*7))  # 1 week, how old configurator_build_status entries should be to get removed
TIME_FORMAT = environ.get('TIME_FORMAT', '%Y-%m-%d %H:%M:%S')

import qmk_redis
from cleanup_storage import cleanup_storage
from qmk_compiler import compile_firmware


# Simple WSGI app to give Rancher a healthcheck to hit
port = 5000
status = {
    'good': ['200 OK', '¡Bueno!\n'],
    'bad': ['500 Internal Server Error', '¡Muy mal!\n'],
    'current': 'bad'
}


class NoLoggingWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


def current_status(i):
    """Return the current status.
    """
    return status[status['current']][i]


def wsgi_app(environ, start_response):
    start_response(current_status(0), [('Content-Type', 'text/plain')])
    return [current_status(1).encode('UTF-8')]


class WebThread(threading.Thread):
    def run(self):
        httpd = make_server('', port, wsgi_app, handler_class=NoLoggingWSGIRequestHandler)
        httpd.serve_forever()


# The main part of the app, iterate over all keyboards and build them.
class TaskThread(threading.Thread):
    def run(self):
        status['current'] = 'good'

        keyboards_tested = qmk_redis.get('qmk_api_keyboards_tested')  # FIXME: Remove when no longer used
        if not keyboards_tested:
            keyboards_tested = {}

        failed_keyboards = qmk_redis.get('qmk_api_keyboards_failed')  # FIXME: Remove when no longer used
        if not failed_keyboards:
            failed_keyboards = {}

        configurator_build_status = qmk_redis.get('qmk_api_configurator_status')
        if not configurator_build_status:
            configurator_build_status = {}

        while True:
            # Cycle through each keyboard and build it
            for keyboard in qmk_redis.get('qmk_api_keyboards'):
                try:
                    metadata = qmk_redis.get('qmk_api_kb_%s' % (keyboard))
                    if not metadata['layouts']:
                        keyboards_tested[keyboard + '/[NO_LAYOUTS]'] = False  # FIXME: Remove when no longer used
                        failed_keyboards[keyboard + '/[NO_LAYOUTS]'] = {'severity': 'error', 'message': '%s: No layouts defined.' % keyboard}  # FIXME: Remove when no longer used
                        configurator_build_status[keyboard + '/[NO_LAYOUTS]'] = {'works': False, 'last_tested': int(time()), 'message': '%s: No Layouts defined.' % keyboard}
                        continue

                    for layout_macro in list(metadata['layouts']):
                        keyboard_layout_name = '/'.join((keyboard,layout_macro))
                        layout = list(map(lambda x:'KC_NO', metadata['layouts'][layout_macro]['layout']))
                        layers = [layout, list(map(lambda x:'KC_TRNS', layout))]

                        # Enqueue the job
                        print('***', strftime('%Y-%m-%d %H:%M:%S'))
                        print('Beginning test compile for %s, layout %s' % (keyboard, layout_macro))
                        job = compile_firmware.delay(keyboard, 'qmk_api_tasks_test_compile', layout_macro, layers)
                        print('Successfully enqueued, polling every 2 seconds...')
                        timeout = time() + COMPILE_TIMEOUT
                        while not job.result:
                            if time() > timeout:
                                print('Compile timeout reached after %s seconds, giving up on this job.' % (COMPILE_TIMEOUT))
                                break
                            sleep(2)

                        # Check over the job results
                        if job.result and job.result['returncode'] == 0:
                            print('Compile job completed successfully!')
                            configurator_build_status[keyboard_layout_name] = {'works': True, 'last_tested': int(time()), 'message': job.result['output']}
                            keyboards_tested[keyboard_layout_name] = True  # FIXME: Remove this when it's no longer used
                            if keyboard_layout_name in failed_keyboards:
                                del(failed_keyboards[keyboard_layout_name])  # FIXME: Remove this when it's no longer used
                        else:
                            print('Could not compile %s, layout %s' % (keyboard, layout_macro))
                            if not job.result:
                                output = 'Job took longer than %s seconds, giving up!' % COMPILE_TIMEOUT
                            else:
                                output = job.result['output']
                            print(output)

                            configurator_build_status[keyboard_layout_name] = {'works': False, 'last_tested': int(time()), 'message': output}
                            keyboards_tested[keyboard_layout_name] = False  # FIXME: Remove this when it's no longer used
                            failed_keyboards[keyboard_layout_name] = {'severity': 'error', 'message': output}  # FIXME: Remove this when it's no longer used

                        # Write our current progress to redis
                        print('\n\n\n\n')
                        qmk_redis.set('qmk_api_configurator_status', configurator_build_status)
                        qmk_redis.set('qmk_api_keyboards_tested', keyboards_tested)
                        qmk_redis.set('qmk_api_keyboards_failed', failed_keyboards)

                except Exception as e:
                    print('***', strftime('%Y-%m-%d %H:%M:%S'))
                    print('Uncaught exception!', e.__class__.__name__)
                    print(e)
                    print_exc()

                # Clean up files on S3 after every build
                print('***', strftime('%Y-%m-%d %H:%M:%S'))
                print('Beginning S3 storage cleanup.')
                job = cleanup_storage.delay()
                print('Successfully enqueued job id %s at %s, polling every 2 seconds...' % (job.id, strftime(TIME_FORMAT)))
                start_time = time()
                while not job.result:
                    if time() - start_time > S3_CLEANUP_TIMEOUT:
                        print('S3 cleanup took longer than %s seconds! Cancelling at %s!' % (S3_CLEANUP_TIMEOUT, strftime(TIME_FORMAT)))
                        break
                    sleep(2)

                # Check over the job results
                if job.result:
                    print('Cleanup job completed successfully!')
                else:
                    print('Could not clean S3!')
                    print(job)
                    print(job.result)

            # Remove stale build status entries
            print('***', strftime('%Y-%m-%d %H:%M:%S'))
            print('Checking configurator_build_status for stale entries.')
            for keyboard_layout_name in configurator_build_status:
                if time() - configurator_build_status[keyboard_layout_name]['last_tested'] > BUILD_STATUS_TIMEOUT:
                    print('Removing stale entry %s because it is %s seconds old' % (keyboard_layout_name, configurator_build_status[keyboard_layout_name]['last_tested']))
                    del(configurator_build_status[keyboard_layout_name])

        print('How did we get here this should be impossible! HELP! HELP! HELP!')
        status['current'] = 'bad'



if __name__ == '__main__':
    w = WebThread()
    t = TaskThread()
    w.start()
    t.start()
