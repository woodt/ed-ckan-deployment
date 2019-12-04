from setuptools import setup

setup(
    name='deploy',
    description='Help manage CKAN deployments',
    version='0.1',
    author='Tom Wood',
    author_email='tom.wood@civicactions.com',
    license='CC',
    packages=['deploy'],
    zip_safe=False,
    install_requires=[
        'click',
        'pyyaml',
        'cerberus',
        'ckanapi'
    ],
    entry_points = {
        'console_scripts': ['deploy=deploy.deploy:main']
    }
)
