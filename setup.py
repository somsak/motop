#!/usr/bin/env python

from setuptools import setup
import libmotop

def readme():
    with open('README.rst') as readmeFile:
        return readmeFile.read()

setup(name=libmotop.__name__,
        version=str(libmotop.__version__),
        packages=('libmotop',),
        scripts=('motop',),
        author='Somsak Sriprayoonsakul',
        author_email='somsaks@gmail.com',
        install_requires=('pymongo', 'argparse'),
        license='ICS',
        url='https://github.com/somsak/motop',
        platforms='POSIX',
        description=libmotop.__doc__,
        keywords='mongo realtime monitoring examine explain kill operations',
        long_description='Top-clone for MongoDB operations')

