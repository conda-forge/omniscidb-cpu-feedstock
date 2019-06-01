"""
Run omniscidb sanity tests one-by-one.
"""
# Author: Pearu Peterson
# Created: June 2019

import os
import re
import sys
import subprocess
from collections import defaultdict

SRC_DIR = os.path.abspath(os.environ.get('SRC_DIR', '.'))
assert os.path.isdir(SRC_DIR), SRC_DIR

sanity_tests = re.search(r'set[(]SANITY_TESTS(.*?)[)]', open(os.path.join(SRC_DIR, 'Tests/CMakeLists.txt')).read(), re.M|re.S).group(1).strip().split()
#sanity_tests = sanity_tests[:1] 
print('sanity_tests: ', ', '.join(sanity_tests))

test_output_dir = os.path.join(SRC_DIR, 'build/Tests/Testing/Temporary/')
test_success_dir = os.path.join(SRC_DIR, 'build/Tests/Testing/Temporary/Success')
test_failure_dir = os.path.join(SRC_DIR, 'build/Tests/Testing/Temporary/Failure')
if not os.path.isdir(test_success_dir):
    os.system('mkdir -vp {}'.format(test_success_dir))
if not os.path.isdir(test_failure_dir):
    os.system('mkdir -vp {}'.format(test_failure_dir))

def filter_thrift_errors(out):
    lines = []
    flag = False
    for line in out.splitlines(True):
        if flag:
            sline = line.lstrip()
            if (sline.startswith('at ')
                or sline.startswith('...')
                or sline.startswith('Caused by: java.net.SocketException')
                or sline.startswith('org.apache.thrift.transport.TTransportException')):
                continue
            flag = False
        if 'Thrift error occurred during processing of message.' in line:
            flag = True
            lines.append(line.rstrip() + '  .....\n')
        else:
            lines.append(line)
    return ''.join(lines)

def get_queries(out):
    queries = []
    last_stars = True
    for line in out.splitlines():
        if line.startswith('ParserWrapper::ParserWrapper:'):
            queries.append(line.split(' ', 1)[1].strip())
    return queries

def system(cmd, timeout = 60*7, stdout=None, stderr=None):
    queries = None
    try:
        p = subprocess.run(list(cmd.split()), timeout=timeout, capture_output=True)
        rcode = p.returncode
        out = p.stdout
        err = p.stderr
    except subprocess.TimeoutExpired as p:
        rcode = -99999
        out = p.stdout
        err = p.stderr
    if stdout is not None and out is not None:
        out = out.decode()
        f = open(stdout, 'w')
        f.write(filter_thrift_errors(out))
        f.close()
        if rcode:
            queries = get_queries(out)
    if stderr is not None and err is not None:
        f = open(stderr, 'wb')
        f.write(err)
        f.close()
    return rcode, queries

# go to build and check that test binary exists:
prevdir = os.getcwd()
os.chdir('build')


# tests that test cases are run one by one. Add only those tests here
# that are certain to fail. The list will be extended if a test fails:
one2one_tests = []
failed_tests = []
while sanity_tests:
    sanity_test = sanity_tests.pop(0)
    
    # find test source:
    test_src = os.path.join(SRC_DIR, 'Tests', sanity_test + '.cpp')
    if not os.path.isfile(test_src):
        test_src = os.path.join(SRC_DIR, 'Tests/Shared', sanity_test + '.cpp')
    assert os.path.isfile(test_src), repr(test_src)

    # collect test cases from sources:
    tests_count = 0
    tests_run_count = 0
    tests = defaultdict(list)
    for line in open(test_src).readlines():
        line = line.lstrip()
        if line.startswith('TEST'):
            i = line.find('(')
            j = line.find(')')
            assert -1 not in [i,j], repr(line)
            test_group, test_name = line[i+1:j].replace(' ','').split(',')
            if not (test_name.startswith('DISABLED') or test_group.startswith('DISABLED')):
                tests[test_group].append(test_name)
                tests_count += 1

    # run the tests
    test_exe = os.path.join(SRC_DIR, 'build/Tests', sanity_test)
    assert os.path.isfile(test_exe), repr(test_exe)
    if sanity_test in one2one_tests:
        sys.stdout.write('Running {} test cases one by one:\n'.format(sanity_test))
        for group_name in tests:
            for test_name in sorted(tests[group_name]):
                tests_run_count += 1
                test_out = os.path.join(test_output_dir, '{}-{}-{}.out'.format(sanity_test, group_name, test_name))
                test_err = os.path.join(test_output_dir, '{}-{}-{}.err'.format(sanity_test, group_name, test_name))
                test_success = os.path.join(test_success_dir, os.path.basename(test_out))
                test_fail = os.path.join(test_failure_dir, os.path.basename(test_out))
                sys.stdout.write('  {}.{} ({} of {})..'.format(group_name, test_name, tests_run_count, tests_count))
                sys.stdout.flush()
                if os.path.isfile(test_success):
                    sys.stdout.write('OK (cached)\n')
                    sys.stdout.flush()
                    continue
                if os.path.isfile(test_fail):
                    sys.stdout.write('FAIL (cached)\n')
                    failed_tests.append('{}-{}-{}'.format(sanity_test, group_name, test_name))
                    queries = get_queries(open(test_fail).read())
                    if queries:
                        sys.stdout.write('    QUERY[{}-{}.{}]: {}\n'.format(sanity_test, group_name, test_name, queries[-1]))
                    sys.stdout.flush()
                    continue
                # macosx does not have timeout
                test_cmd = '{} --gtest_filter={}.{}'.format(test_exe, group_name, test_name)
                status, queries = system(test_cmd, stdout=test_out, stderr=test_err)
                if status == 0:
                    os.system('mv {} {}'.format(test_out, test_success_dir))
                    os.system('mv {} {}'.format(test_err, test_success_dir))
                    sys.stdout.write('OK\n')
                else:
                    os.system('echo "RETURN STATUS: {}" >> {}'.format(status, test_out))
                    os.system('mv {} {}'.format(test_out, test_failure_dir))
                    os.system('mv {} {}'.format(test_err, test_failure_dir))
                    if status == -99999:
                        sys.stdout.write('TIMEOUT\n')
                    else:
                        sys.stdout.write('FAIL[{}]\n'.format(status))
                    if queries:
                        sys.stdout.write('    QUERY[{}-{}.{}]: {}\n'.format(sanity_test, group_name, test_name, queries[-1]))
                    failed_tests.append('{}-{}-{}'.format(sanity_test, group_name, test_name))
                sys.stdout.flush()
    else: # not one to one tests
        sys.stdout.write('Running {}..'.format(sanity_test))
        sys.stdout.flush()
        test_out = os.path.join(test_output_dir, '{}.out'.format(sanity_test))
        test_err = os.path.join(test_output_dir, '{}.err'.format(sanity_test))
        test_success = os.path.join(test_success_dir, os.path.basename(test_out))
        test_fail = os.path.join(test_failure_dir, os.path.basename(test_out))
        if os.path.isfile(test_success):
            sys.stdout.write('OK (cached)\n')
        elif os.path.isfile(test_fail):
            sys.stdout.write('FAIL (cached)\n')
            failed_tests.append('{}'.format(sanity_test))
            # re-run test one by one:
            sanity_tests.append(sanity_test)
            one2one_tests.append(sanity_test)
        else:
            test_cmd = '{}'.format(test_exe)
            status, queries = system(test_cmd, stdout=test_out, stderr=test_err, timeout=60*20)
            if status == 0:
                os.system('mv {} {}'.format(test_out, test_success_dir))
                os.system('mv {} {}'.format(test_err, test_success_dir))
                sys.stdout.write('OK\n')
            else:
                os.system('echo "RETURN STATUS: {}" >> {}'.format(status, test_out))
                os.system('mv {} {}'.format(test_out, test_failure_dir))
                os.system('mv {} {}'.format(test_err, test_failure_dir))
                if status == -99999:
                    sys.stdout.write('TIMEOUT\n')
                else:
                    sys.stdout.write('FAIL[{}]\n'.format(status))
                failed_tests.append('{}'.format(sanity_test))
                # re-run test one by one:
                sanity_tests.append(sanity_test)
                one2one_tests.append(sanity_test)
        sys.stdout.flush()

# leave build
os.chdir(prevdir)


os.system('echo "SUCCEEDED TESTS COUNT: `ls {}/*.out | wc -w`"'.format(test_success_dir))
os.system('echo "FAILED TESTS COUNT: `ls {}/*.out | wc -w`"'.format(test_failure_dir))
if failed_tests:
    sys.exit(1)
