#! /usr/bin/env python

import click
import logging
from yaml import load, FullLoader
import os
from cerberus import Validator
import subprocess
import pwd
import grp

FORMAT = '%(asctime)-15s %(levelname)s [%(module)s] %(message)s'
logger = logging.getLogger(__name__)

# deploy -c config.yaml [--dry-run] deployment.yaml

def user_changer(uid, gid):
    def fn():
        os.setgid(gid)
        os.setuid(uid)
    return fn

class Deployer(object):

    def __init__(self, config, deployment):
        self.config = config
        self.deployment = deployment
        self.uid = pwd.getpwnam(config['user']).pw_uid
        self.gid = grp.getgrnam(config['group']).gr_gid

    def execute(self, dry_run):
        logger.info("Deploying to %s", self._name())
        for operation in self.deployment['deployment']:
            if 'install' in operation:
                for install in operation['install']:
                    cmd = self._pip_install(install)
                    self._execute(cmd, dry_run, fail_on_error=install.get('fail_on_error', True))
            elif 'uninstall' in operation:
                for uninstall in operation['uninstall']:
                    cmd = self._pip_uninstall(uninstall)
                    self._execute(cmd, dry_run, fail_on_error=uninstall.get('fail_on_error', True))
            elif 'paster' in operation:
                cmd = self._paster_cmd(operation['paster'])
                self._execute(cmd, dry_run)

        cmd = self._restart()
        self._execute(cmd, dry_run, root=True)
        
    def _execute(self, cmd, dry_run, root=False, fail_on_error=True):
        if dry_run:
            prefix = "DRY RUN: "
        else:
            prefix = ""
            
        if root:
            user = "root"
        else:
            user = "%s:%s" % (self._user(), self._group())
                
        logger.info("%s(AS %s) %s", prefix, user, ' '.join(cmd))

        if not dry_run:
            try:
                if root:
                    output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                else:
                    output = subprocess.check_output(cmd, stderr=subprocess.STDOUT,
                                                     preexec_fn=user_changer(self.uid, self.gid))
                print output
            except subprocess.CalledProcessError, e:
                logger.warning("Command %s returned exit code %d\n%s", e.cmd, e.returncode)
                print e.output
                if fail_on_error:
                    raise
            except Exception, e:
                logger.error("Could not execute command '%s': %s",' '.join(cmd), str(e))
                raise

    def _name(self):
        return self.config['name']
    
    def _user(self):
        return self.config['user']
    
    def _group(self):
        return self.config['group']
    
    def _restart(self):
        return self.config['restart'].split(' ')
        
    def _pip_install(self, pip):
        if 'src' in pip:
            return self._pip_install_src(pip)
        else:
            return self._pip_install_package(pip)

    def _pip_install_src(self, pip):
        cmd = [self._virtualenv_cmd('pip'), "install", "-U", "-e", self._pip_requirement(pip)
        ]
        return cmd

    def _pip_install_package(self, pip):
        requirement = '{}=={}'.format(pip['name'], pip['version'])
        cmd = [self._virtualenv_cmd('pip'), 'install', '-U', requirement]
        return cmd


    def _pip_uninstall(self, pip):
        cmd = [self._virtualenv_cmd('pip'), "uninstall", pip['name']]
        return cmd
    
    def _virtualenv_cmd(self, cmd):
        return os.path.join(self.config['virtualenv'], 'bin', cmd)

    def _pip_requirement(self, pip):
        return "{src}@{tag}#egg={name}".format(**pip)
    
    def _pip_freeze(self):
        return [self._virtualenv_cmd('pip'), 'freeze']
        
    def _paster_cmd(self, paster):
        cmd = [
            self._virtualenv_cmd('paster'), 
            '--plugin', paster['plugin'],
        ]
        cmd += paster['command'].split(' ')
        cmd += ['--config', self.config['config']]

        return cmd
    
@click.command()
@click.option('--config', '-c', 'config_yaml',
              type=click.File('r'),
              default='config.yaml',
              help='Name of the configuration file')
@click.option('--dry-run', '-n', 
              type=click.BOOL,
              is_flag=True,
              help='Print commands that would be executed')
@click.argument('deployment_yaml',
                metavar='deployment', type=click.File('r'))
def main(config_yaml, dry_run, deployment_yaml):
    logging.basicConfig(format=FORMAT, level=logging.INFO)
    config = load(config_yaml, Loader=FullLoader)
    config, errors = validate_config(config)
    if errors:
        raise click.ClickException(validation_msg("configuration file", errors))
    
    deployment = load(deployment_yaml, Loader=FullLoader)
    deployment, errors = validate_deployment(deployment)
    if errors:
        raise click.ClickException(validation_msg("deployment file", errors))
    deploy(config, deployment, dry_run)
    
def deploy(config, deployment, dry_run):
    deployer = Deployer(config, deployment)
    deployer.execute(dry_run)
    
def validate_config(config):
    schema = {
        'name': {'type': 'string', 'required': True},
        'restart': {'type': 'string', 'required': True},
        'virtualenv': {'type': 'string', 'required': True},
        'config': {'type': 'string', 'required': True},
        'user': {'type': 'string', 'required': True},
        'group': {'type': 'string', 'required': True}
    }

    v = Validator(schema)
    if v.validate(config):
        return (v.normalized(config), False)
    else:
        return (config, v.errors)
    
        # 'install': {
        #     'type': 'list',
        #     'schema': {
        #         'name': {
        #             'type': 'string',
        #             'required': True
        #         },
        #         'src': {
        #             'type': 'string'
        #         },
        #         'tag': {
        #             'type': 'string'
        #         },
        #         'version': {
        #             'type': 'string'
        #         },
        #         'fail_on_error': { 
        #             'type': 'boolean',
        #             'default': True
        #         }
        #     }
        # }

def validate_deployment(deployment):
    install_schema =  {
        'name': {
            'type': 'string',
            'required': True
        },
        'src': {
            'type': 'string'
        },
        'tag': {
            'type': 'string'
        },
        'version': {
            'type': 'string'
        },
        'fail_on_error': {
            'type': 'boolean'
        }
    }

    command_schemas = [
        {
            'install': {
                'type': 'list',
                'schema': {
                    'type': 'dict',
                    'schema': install_schema
                }
            }
        },
        {
            'uninstall': {
                'type': 'list',
                'schema': {
                    'type': 'dict',
                    'schema': {
                        'name': { 'type': 'string', 'required': True },
                        'fail_on_error': { 'type': 'boolean' }
                    }
                }
            }
        },
        {
            'paster': {
                'type': 'dict',
                'schema': {
                    'plugin': { 'type': 'string' },
                    'command': { 'type': 'string' }
                }
            }
        }
    ]

    schema = {
        'deployment': {
            'type': 'list',
            'schema': {
                'type': 'dict',
                'oneof_schema': command_schemas
            }
        }
    }
    
                # 'schema': {
                #     'oneof_schema': command_schemas
                # }

    v = Validator(schema)
    if v.validate(deployment):
        return (v.normalized(deployment), False)
    else:
        return (deployment, v.errors)
    
def validation_msg(path, errors):

    def _validation_msg(errors):
        if isinstance(errors, dict):
            for key, value in errors.items():
                _validation_msg.field_errors += "%s." % key
                _validation_msg(value)
        elif isinstance(errors, list):
            for i in errors:
                _validation_msg(i)
        else:
            _validation_msg.field_errors += '"%s"' % errors

    _validation_msg.field_errors = "Validation error(s) in %s: " % path

    _validation_msg(errors)

    return _validation_msg.field_errors

if __name__ == '__main__':
    main()
