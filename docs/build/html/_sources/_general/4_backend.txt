**************
Backend
**************

Project on the server
----------------------

The path to the project on the server.

::

$ /home/gsi/sites/gsi_website


Restart the server from the local computer
------------------------------------------

Source code the GSi project is in the repository. For the project management need to clone it to your local computer in the home folder:

::

$ cd /home/[user]
$ git clone https://github.com/gtsarik/GSI.git


After cloning the project you want to add a new file fab_local.py:

::

$ cd GSI
$ touch fab_local.py

Open the fab_local.py file:

::

$ vim fab_local.py

and add 3 variables in it:

::

$ GSI_APP_SERVER = 'gsi@indy4.epcc.ed.ac.uk'
$ REMOTE_CODE_DIR = [remote root folder of the project]
$ ENV_PASS = 'password to login on ssh'

The example for the REMOTE_CODE_DIR variable. The GSi project is along this path: /home/gsi/sites/gsi_website, so REMOTE_CODE_DIR = 'sites/gsi_website'

Save and close the file fab_local.py. Reboot the server:

::

$ make restart


Restart the server remotely
----------------------------

::

$ ssh gsi@indy4.epcc.ed.ac.uk
$ [enter password]
$ sudo service supervisor restart
$ [enter password]
