#!/usr/bin/env python
# -*- coding: utf8 -*-
#
# Copyright (c) 2009 Erdem U. Altinyurt <spamjunkeater@gmail.com>
# Based On:
# Copyright (c) 2007 Can Berk Güder <cbguder@su.sabanciuniv.edu>
#
# This file is part of DiskIOSpace Screenlet.
#
# Disk Space Screenlet is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Disk Space Screenlet is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Disk Space Screenlet; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301
# USA

#v0.5
#Added auto mount /media
#Added auto mount for easy start
#Fixed freze on new mount.

#v0.6
#Fixed IO loads if intervals bigger than 1 second
#Try to fix Clicks Enabled bug.

#v0.7
#Added RAID device load support.

import screenlets
from screenlets.options import BoolOption, ColorOption, IntOption, ListOption, Option
import cairo
import pango
import subprocess
import gobject
import gtk
import os

import gzip
import time
from math import ceil

DRIVE_HEIGHT = 50
PADDING      = 8

def load(quota):
	load = int(quota.replace('%',''))

	if load > 99: load = 99
	elif load < 0: load = 0

	return load

def nickname(mount):
	if mount == '/':
		return mount

	return mount[mount.rfind('/')+1:]

class ioloadstat(object):  #Erdem U. Altinyurt Disk I/O meter class
	def __init__ (self):
		self.diskstat = open( '/proc/diskstats', 'r' )
		self.bufold=[]
		self.timeold = time.time()
		afile = open( '/proc/timer_list')
		the_HZ=''
		for line in afile.read().split('\n'):
			if( line.startswith('  .resolution:')):
				the_HZ = line;
				break;
		afile.close()
		resolution = int(the_HZ[the_HZ.find(': ')+2:the_HZ.rfind(' ')])
		self.CONFIG_HZ = 1000/resolution
		print "CONFIG_HZ =", self.CONFIG_HZ

	def read(self): # returns a list that includes ('device_name, float_load_percentage )
		self.diskstat.seek(0)
		buff = self.diskstat.read().split('\n')
		bufnew = []
		for i in buff:
			a = i.split()
			if len(a) > 12:
				bufnew.append((a[2], int(a[12])) )	#name and device IO

		if len(self.bufold) == 0:
			self.bufold = bufnew

		timenew = time.time()
		bufd = {} #is in {sda1 : 96} elemets indicates sda1 has %96 load
		if len( self.bufold ) == len( bufnew ):
			for i in range(0,len(bufnew)):
				bufd[bufnew[i][0]] = (float (bufnew[i][1] - self.bufold[i][1]))/((self.CONFIG_HZ / 100.0)*(timenew - self.timeold))
		else:
			for bn in bufnew:
				for bo in self.bufold:
					if bo[0] == bn[0]:   #match devices via name
						bufd[bo[0]] = (float (bn[1] - bo[1]))/((self.CONFIG_HZ / 100.0)*(timenew - self.timeold))
		self.bufold = bufnew
		self.timeold = timenew
		#reconstructing md devices from real devices
		if os.path.exists('/proc/mdstat'):
			mddevs = {}
			j = [ m for m in open('/proc/mdstat','rt').read().split('\n') if m.startswith("md")]
			for a in j:
				mddevs[ a.split()[0] ] = [ x.split('[')[0] for x in a.split()[4:] ]

			for md in mddevs: #updating md devices load
				mx=0.0
				for i in mddevs[md]:
					mx = max( bufd[i], mx ) #calculating load by taking devices load whic is maximum. It's correct for Raid0 read/write and RAID1 write But Raid1 Read, which needed to be balanced.
				bufd[md] = mx
			del mddevs
		del bufnew,timenew,buff
		return bufd

class DiskIOSpaceScreenlet(screenlets.Screenlet):
	"""A screenlet that displays free/used space and I/O information for selected hard drives."""

	# Default Meta-Info for Screenlets
	__name__    = 'Disk I/O Space Screenlet'
	__version__ = '0.7'
	__author__  = 'Erdem U. Altinyurt (based on DiskSpace Screenlet by Can Berk Güder)'
	__desc__    = __doc__

	# Internals
	__timeout     = None
	p_layout      = None
	drive_clicked = -1
	__info        = [{ 'mount': '', 'nick': '', 'free': 0, 'size': 0, 'quota': 0, 'load': 0, 'io_dev' : 0, 'io_part' : 0  }]
	iostat 	 	  = ioloadstat()

	# Default Settings
	clicks_enabled     = False
	stack_horizontally = False
	io_statistics      = True
	io_device          = True
	io_ledbar          = True
	update_interval    = 1
	mount_points       = ['']
	media_mounts       = True
	mount_all			 = False
	threshold          = 80

	color_part_io  = (0.0, 1.0,  0.0,   1.0)
	color_dev_io   = (1.0, 0.0,  0.0,   0.6)
	color_normal   = (0.0, 0.69, 0.94,  1.0)
	color_critical = (1.0, 0.2,  0.545, 1.0)
	color_text     = (0.0, 0.0,  0.0,   0.6)
	frame_color    = (1.0, 1.0,  1.0,   1.0)

	def __init__(self, **keyword_args):
		"""Constructor"""
		# call super
		screenlets.Screenlet.__init__(self, width=220, height=DRIVE_HEIGHT + 2 * PADDING, uses_theme=True, **keyword_args)

		# set theme
		self.theme_name = 'default'

		# add options
		self.add_options_group('DiskSpace', 'DiskSpace specific options')
		self.add_option(BoolOption('DiskSpace', 'clicks_enabled', self.clicks_enabled, 'Clicks Enabled',
			'If checked, clicking on a drive icon opens the drive in Nautilus'))
		self.add_option(BoolOption('DiskSpace', 'stack_horizontally',
			self.stack_horizontally, 'Stack Horizontally',
			'If checked, drives will stack horizontally'))
		self.add_option(IntOption('DiskSpace', 'update_interval',
			self.update_interval, 'Update Interval',
			'The interval for updating the Disk usage (in seconds) ...',
			min=1, max=60))
		self.add_option(BoolOption('DiskSpace', 'media_mounts',
			self.media_mounts, 'Auto Add Media Mounts',
			'Add the mounts at /media directory automaticaly.' ))
		self.add_option( BoolOption('DiskSpace', 'mount_all',
			self.mount_all, 'Add All Mounts Now',
			'Add all mounts to Mount Points list now.'))
		self.add_option(ListOption('DiskSpace', 'mount_points',
			self.mount_points, 'Mount Points',
			'Python-style list of mount points for the devices you want to show'))
		self.add_option(IntOption('DiskSpace', 'threshold',
			self.threshold, 'Threshold',
			'The percentage threshold to display cricital color',
			min=0, max=100))
		self.add_option(ColorOption('DiskSpace', 'color_normal', self.color_normal, 'Normal Color',
			'The color to be displayed when drive usage is below the threshold'))
		self.add_option(ColorOption('DiskSpace', 'color_critical', self.color_critical, 'Critical Color',
			'The color to be displayed when drive usage is above the threshold'))
		self.add_option(ColorOption('DiskSpace', 'color_text', self.color_text, 'Text Color', ''))
		self.add_option(ColorOption('DiskSpace', 'frame_color', self.frame_color, 'Frame Color', ''))

		self.add_options_group('Disk I/O Space', 'DiskIOSpace specific options')
		self.add_option(BoolOption('Disk I/O Space', 'io_statistics', self.io_statistics, 'I/O Statistics','Shows I/O Statistics of a drive' ))
		self.add_option(BoolOption('Disk I/O Space', 'io_ledbar', self.io_ledbar, 'I/O LedBar Style','Shows I/O Statistics as led bar.' ))
		self.add_option(BoolOption('Disk I/O Space', 'io_device', self.io_device, 'Show I/O of Real Device','Shows dependend device I/O gauge at background of partition I/O gauge.' ))
		self.add_option(ColorOption('Disk I/O Space', 'color_drive', self.color_dev_io, 'Device I/O Color',
			'The color to be displayed as drive I/O utilization'))
		self.add_option(ColorOption('Disk I/O Space', 'color_part', self.color_part_io, 'Partition I/O Color',
			'The color to be displayed as partition I/O utilization'))
		self.add_default_menuitems()
		self.update_interval = self.update_interval

	def on_after_set_atribute(self, name, value):
		if name == 'update_interval':
			self.on_set_update_interval()
		elif name == 'mount_points':
			self.on_set_mount_points()
		elif name == 'mount_all':
			self.on_set_mount_all()
		elif name == 'stack_horizontally':
			self.on_set_stack_horizontally()
		else:
			self.update_graph()

	def on_set_update_interval(self):
		if self.update_interval <= 0:
			self.update_interval = 1
		if self.__timeout:
			gobject.source_remove(self.__timeout)
		self.__timeout = gobject.timeout_add(int(self.update_interval * 1000), self.timeout)

	def on_set_mount_points(self):
		for i, mp in enumerate(self.mount_points):
			mp = mp.strip()
			if mp != '/':
				mp = mp.rstrip('/')
			self.mount_points[i] = mp

		self.timeout()

	def on_set_mount_all(self):
		if self.mount_all:
			self.mount_all = False
			for i in range( 0,len(self.mount_points) ): #clearing
				x = self.mount_points.pop()

			proc = subprocess.Popen('df -hP', shell='true', stdout=subprocess.PIPE)
			sdevs = proc.stdout.read().split('\n')
			del proc
			sdevs = sdevs[1:-1]
			for stdev in sdevs:
				sdev = stdev.split()
				if sdev[5] != '/dev':
					self.mount_points.append( sdev[5] )
			del sdevs
			self.session.backend.save_option( self.id , 'mount_points', self.mount_points ) #save the list to disk
			print 'self.id=', self.id
			self.session.backend.flush()


		self.timeout()

	def on_set_stack_horizontally(self):
		self.recalculate_size()
		self.update_graph()

	def recalculate_size(self):
		if self.stack_horizontally:
			self.width  = 220 * len(self.__info)
			self.height = DRIVE_HEIGHT + 2 * PADDING
		else:
			self.width  = 220
			self.height = DRIVE_HEIGHT * len(self.__info) + 2 * PADDING

		if self.window:
			self.window.resize(int(self.width * self.scale), int(self.height * self.scale))

	def get_drive_info(self):
		result = []
		temp = {}
		proc = subprocess.Popen('df -hP', shell='true', stdout=subprocess.PIPE)
		sdevs = proc.stdout.read().split('\n')
		sdevs = sdevs[1:-1]
		if self.io_statistics:
			iodevs = self.iostat.read()

		for stdev in sdevs:
			sdev = stdev.split()
			io_part = '0'
			io_dev = '0'
			if self.io_statistics:
				x = sdev[0].split('/')
				if len( x ) > 1:
					if x[2] in iodevs:
						io_part = iodevs[x[2]]
					if x[2][:-1] in iodevs:
						io_dev = iodevs[x[2][:-1]]

			dev = {
				'device': sdev[0],
				'size'  : sdev[1],
				'used'  : sdev[2],
				'free'  : sdev[3],
				'quota' : sdev[4],
				'mount' : sdev[5],
				'nick'  : nickname(sdev[5]),
				'load'  : load(sdev[4]),
				'io_dev' : io_dev,
				'io_part': io_part
			}

			if dev['mount'] in self.mount_points:
				temp[dev['mount']] = dev
			elif dev['device'] in self.mount_points:
				temp[dev['device']] = dev
			elif self.media_mounts and dev['mount'].startswith( '/media/' ):
				temp[dev['mount']] = dev

		#make them ordered?
		for mp in self.mount_points:
			try:
				result.append(temp[mp])
			except KeyError:
				pass
		#add /media dir mounts those not in the list
		if self.media_mounts:
			for mm in temp:
				if mm not in self.mount_points:
					try:
						result.append( temp[mm] )
					except KeyError:
						pass
		return result

	def update_graph(self):
		self.redraw_canvas()
		return True

	def timeout(self):
		self.__info = self.get_drive_info()
		self.recalculate_size()
		self.update_graph()
		return True

	def on_draw(self, ctx):
		ctx.scale(self.scale, self.scale)
		ctx.set_operator(cairo.OPERATOR_OVER)

		gradient = cairo.LinearGradient(0, self.height*2,0, 0)
		gradient.add_color_stop_rgba(1,*self.frame_color)
		gradient.add_color_stop_rgba(0.7,self.frame_color[0],self.frame_color[1],self.frame_color[2],1-self.frame_color[3]+0.5)
		ctx.set_source(gradient)
		self.draw_rectangle_advanced (ctx, 0, 0, self.width-12, self.height-12, rounded_angles=(5,5,5,5), fill=True, border_size=2, border_color=(0,0,0,0.5), shadow_size=6, shadow_color=(0,0,0,0.5))

		ctx.translate(0, PADDING)
		for i in range(len(self.__info)):
			self.draw_device(ctx, self.__info[i])

			if self.stack_horizontally:
				ctx.translate(220, 0)
			else:
				ctx.translate(0, DRIVE_HEIGHT)

	def draw_device(self, ctx, dev):
		# draw text
		ctx.save()
		ctx.translate(65, 5)

		if self.p_layout == None :
			self.p_layout = ctx.create_layout()
		else:
			ctx.update_layout(self.p_layout)

		p_fdesc = pango.FontDescription()
		p_fdesc.set_family("Free Sans")
		p_fdesc.set_size(10 * pango.SCALE)
		self.p_layout.set_font_description(p_fdesc)

		markup = "<b>%(nick)s</b>\n<b>%(free)s</b> free of <b>%(size)s - %(quota)s</b>\n\n" % dev

		self.p_layout.set_markup(markup)
		ctx.set_source_rgba(*self.color_text)
		ctx.show_layout(self.p_layout)
		ctx.fill()
		ctx.restore()
		ctx.save()
		if self.io_statistics :
			if self.io_ledbar :
				if self.io_device :
					ctx.save()
					ctx.translate(8,-1)
					self.DrawGaugeSoundBar( ctx, 10, 41, 0.3, ceil(float( dev['io_dev'])/10) )
					ctx.restore()

				ctx.save()
				ctx.translate(8,-1)
				self.DrawGaugeSoundBar( ctx, 10, 41, 1.0, ceil(float( dev['io_part'])/10) )
				ctx.restore()

			else:
				if self.io_device :
					w = 190.0 * float( dev['io_dev'] ) / 100.0
					ctx.rectangle(14, 37, w, 10)
					ctx.set_source_rgba(*self.color_dev_io)
					ctx.fill()

				w = 190.0 * float( dev['io_part'] ) / 100.0
				ctx.rectangle(14, 37, w, 10)
				ctx.set_source_rgba(*self.color_part_io)
				ctx.fill()


#		ctx.save()
#		ctx.translate(200,37)
#		ctx.rotate( 90*3.1415/180 )
#		self.DrawGaugeSoundBar( ctx, 10, 190.0 , ceil(float( dev['io_part'])/10) )
#		ctx.restore()

		w = 190.0 * dev['load'] / 100.0
		ctx.rectangle(14, 39, w, 6)
		if dev['load'] < self.threshold:
			ctx.set_source_rgba(*self.color_normal)
		else:
			ctx.set_source_rgba(*self.color_critical)
		ctx.fill()

		ctx.save()
		self.draw_icon(ctx, 20, 0, gtk.STOCK_HARDDISK, 40, 40)
		ctx.restore()

	def on_draw_shape(self, ctx):
		if self.stack_horizontally:
			ctx.rectangle(0, 0, (220 * len(self.__info) + 2 * PADDING) * self.scale, (DRIVE_HEIGHT +  2 * PADDING) * self.scale)
		else:
			ctx.rectangle(0, 0, 220 * self.scale, (DRIVE_HEIGHT * len(self.__info) + 2 * PADDING) * self.scale)

		ctx.fill()

	def on_mouse_down(self, event):
		if self.clicks_enabled and event.button == 1:
			if event.type == gtk.gdk.BUTTON_PRESS:
				return self.detect_button(event.x, event.y)
			else:
				return True
		else:
			return False

	def on_mouse_up(self, event):
		if self.clicks_enabled and self.__drive_clicked >= 0:
			os.system('nautilus --sm-client-disable --no-desktop -n "%s" &' % self.__info[self.__drive_clicked]['mount'])
			self.__drive_clicked = -1
		return False

	def detect_button(self, x, y):
		x /= self.scale
		y /= self.scale

		drive_clicked = -1

		if x >= 15 and x <= 52:
			if y%DRIVE_HEIGHT >= 4 and y%DRIVE_HEIGHT <= 30:
				drive_clicked = int(y)/DRIVE_HEIGHT

		self.__drive_clicked = drive_clicked

		if drive_clicked >= 0:
			return True
		else:
			return False

	#Draw Soundbar like vertical gauge
	def DrawGaugeSoundBar(self, cr, width, height, transp, level):
			#cr.set_source_rgb( 0,0,0 )
			#cr.rectangle(0, 0, width, height)
			#cr.fill()

			rgb = [0.0, 1.0, 0.0, transp]
			step = 10
			middle_point = 5
			#space = (height/step)*(30.0/100)
			space = 1
			bar_height = (height-(step+1)*space)/step
			stp = 1
			#level = 10

			while stp <= middle_point and stp <= level:
				cr.rectangle(space, height-(bar_height+space)*stp, width-space*2, bar_height )
				cr.set_source_rgba( rgb[0], rgb[1], rgb[2], rgb[3] )
				cr.fill()
				rgb[0] += 1.0/(middle_point-1)
				stp += 1

			rgb[0] -= 1.0/(middle_point-1)	#last step unnecessaryly add this

			while stp <= step and stp <= level :
				rgb[1] -=  1.0/(step-middle_point)
				cr.rectangle(space, height-(bar_height+space)*stp, width-space*2, bar_height )
				cr.set_source_rgba( rgb[0], rgb[1], rgb[2], rgb[3] )
				cr.fill()
				stp += 1


# If the program is run directly or passed as an argument to the python
# interpreter then create a Screenlet instance and show it
if __name__ == "__main__":
	import screenlets.session
	screenlets.session.create_session(DiskIOSpaceScreenlet)
