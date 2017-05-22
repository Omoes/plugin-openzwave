#!flask/bin/python
import sys
import binascii
import logging
from lxml import etree
import globals,utils,network_utils,node_utils
import value_utils,commands
from utilities.Constants import *
from utilities.NetworkExtend import *
try:
	from flask import Flask, jsonify, abort, request, make_response, redirect, url_for
	from flask_httpauth import HTTPBasicAuth
except Exception as e:
	print(globals.MSG_CHECK_DEPENDENCY, 'error')
	print("Error: %s" % str(e), 'error')
	sys.exit(1)

auth = HTTPBasicAuth()
globals.app = app = Flask(__name__, static_url_path='/static')

@app.before_first_request
def _run_on_start():
	pass

@app.errorhandler(400)
def not_found400(error):
	logging.error('%s %s' % (error, request.url))
	return utils.format_json_result(success='error', data='Bad request')

@app.errorhandler(404)
def not_found404(error):
	logging.error('%s %s' % (error, request.url))
	return utils.format_json_result(success='error', data='Not found')

@app.teardown_appcontext
def close_network(error):
	if error is not None:
		logging.error('%s %s' % (error, 'teardown'))

@app.errorhandler(Exception)
def unhandled_exception(exception):
	return utils.format_json_result(success='error', data=str(exception))

@auth.verify_password
def verify_password(username, password):
	return password == globals.apikey

@app.route('/controller/replicationSend(<node_id>)', methods=['GET'])
@auth.login_required
def replication_send(node_id):
	if not network_utils.can_execute_network_command(0):
		raise Exception('Controller is bussy')
	utils.check_node_exist(node_id)
	logging.info('Send information from primary to secondary %s' % (node_id,))
	return utils.format_json_result(data=globals.network.manager.replicationSend(globals.network.home_id, node_id))

@app.route('/controller/info(<info>)', methods=['GET'])
@auth.login_required
def controller_info(info):
	logging.info("Controller info "+str(info))
	return utils.format_json_result()

@app.route('/controller/action(<action>)', methods=['GET'])
@auth.login_required
def controller_action(action):
	logging.info("Controller action "+str(action))
	if action in globals.CONTROLLER_REST_MAPPING:
		return globals.CONTROLLER_REST_MAPPING[action]()
	else:
		return utils.format_json_result()

@app.route('/controller/addNodeToNetwork(<int:state>,<int:do_security>)', methods=['GET'])
@auth.login_required
def start_node_inclusion(state, do_security):
	if globals.network_information.controller_is_busy:
		raise Exception('Controller is bussy')
	if state == 1:
		if not network_utils.can_execute_network_command(0):
			raise Exception('Controller is bussy')
		if do_security == 1:
			do_security = True
			logging.info(
				"Start the Inclusion Process to add a Node to the Network with Security CC if the node is supports it")
		else:
			do_security = False
			logging.info("Start the Inclusion Process to add a Node to the Network")
		execution_result = globals.network.manager.addNode(globals.network.home_id, do_security)
		if execution_result:
			globals.network_information.actual_mode = ControllerMode.AddDevice
		return utils.format_json_result(data=execution_result)
	elif state == 0:
		logging.info("Start the Inclusion (Cancel)")
		globals.network.manager.cancelControllerCommand(globals.network.home_id)
		return utils.format_json_result()

@app.route('/controller/removeNodeFromNetwork(<int:state>)', methods=['GET'])
@auth.login_required
def start_node_exclusion(state):
	if globals.network_information.controller_is_busy:
		raise Exception('Controller is bussy')
	if state == 1:
		if not network_utils.can_execute_network_command(0):
			raise Exception('Controller is bussy')
		logging.info("Remove a Device from the Z-Wave Network (Started)")
		execution_result = globals.network.manager.removeNode(globals.network.home_id)
		if execution_result:
			globals.network_information.actual_mode = ControllerMode.RemoveDevice
		return utils.format_json_result(data=execution_result)
	elif state == 0:
		logging.info("Remove a Device from the Z-Wave Network (Cancel)")
		globals.network.manager.cancelControllerCommand(globals.network.home_id)
		return utils.format_json_result()	

@app.route('/network/action(<action>)', methods=['GET'])
@auth.login_required
def network_action(action):
	if action in globals.NETWORK_REST_MAPPING:
		return globals.NETWORK_REST_MAPPING[action]()
	else:
		return utils.format_json_result()

@app.route('/network/info(<info>)', methods=['GET'])
@auth.login_required
def network_info(info):
	if info in globals.NETWORK_REST_MAPPING:
		return globals.NETWORK_REST_MAPPING[info]()
	else:
		return utils.format_json_result()

@app.route('/node/<int:node_id>/info(<info>)', methods=['GET'])
@auth.login_required
def node_info(node_id,info):
	utils.check_node_exist(node_id)
	logging.info("node info "+str(info))
	if info in globals.NODE_REST_MAPPING:
		return globals.NODE_REST_MAPPING[info](node_id)
	else:
		return utils.format_json_result()

@app.route('/node/<int:node_id>/action(<action>)', methods=['GET'])
@auth.login_required
def node_action(node_id,action):
	utils.check_node_exist(node_id)
	utils.check_network_can_execute()
	logging.info("node action "+str(action))
	if action in globals.NODE_REST_MAPPING:
		return globals.NODE_REST_MAPPING[action](node_id)
	else:
		return utils.format_json_result()

@app.route('/node/<int:node_id>/cc/<int:cc_id>/refreshClass()', methods=['GET'])
@auth.login_required
def request_all_config_params(node_id,cc_id):
	utils.check_node_exist(node_id)
	logging.info('Request values refresh for '+str(node_id)+' on class '+str(cc_id))
	for val in globals.network.nodes[node_id].get_values(class_id=cc_id):
		configuration_item = globals.network.nodes[node_id].values[val]
		if configuration_item.id_on_network in globals.pending_configurations:
			del globals.pending_configurations[configuration_item.id_on_network]
	globals.network.manager.requestAllConfigParams(globals.network.home_id, node_id)
	return utils.format_json_result()

@app.route('/node/<int:node_id>/removeDeviceZWConfig(<int:identical>)', methods=['GET'])
@auth.login_required
def remove_device_openzwave_config(node_id, identical):
	utils.check_node_exist(node_id)
	my_node = globals.network.nodes[node_id]
	manufacturer_id = my_node.manufacturer_id
	product_id = my_node.product_id
	product_type = my_node.product_type
	list_to_remove = [node_id]
	if identical != 0:
		for child_id in list(globals.network.nodes):
			node = globals.network.nodes[child_id]
			if child_id != node_id and node.manufacturer_id == manufacturer_id and node.product_id == product_id and node.product_type == product_type:
				list_to_remove.append(child_id)
	globals.network_is_running = False
	globals.network.stop()
	logging.info('ZWave network is now stopped')
	time.sleep(5)
	filename = globals.data_folder + "/zwcfg_" + globals.network.home_id_str + ".xml"
	tree = etree.parse(filename)
	for child_id in list_to_remove:
		logging.info("Remove xml element for node %s" % (child_id,))
		node = tree.find("{http://code.google.com/p/open-zwave/}Node[@id='" + str(child_id) + "']")
		tree.getroot().remove(node)
	working_file = open(filename, "w")
	working_file.write('<?xml version="1.0" encoding="utf-8" ?>\n')
	working_file.writelines(etree.tostring(tree, pretty_print=True))
	working_file.close()
	network_utils.start_network()
	return utils.format_json_result()

@app.route('/node/<int:source_id>/copyConfigurations(<int:target_id>)', methods=['GET'])
@auth.login_required
def copy_configuration(source_id, target_id):
	if globals.network_information.controller_is_busy:
		raise Exception('Controller is bussy')
	logging.info("copy_configuration from source_id:%s to target_id:%s" % (source_id, target_id,))
	items = 0
	utils.check_node_exist(source_id)
	utils.check_node_exist(target_id)
	source = globals.network.nodes[source_id]
	target = globals.network.nodes[target_id]
	if source.manufacturer_id != target.manufacturer_id or source.product_type != target.product_type or source.product_id != target.product_id:
		raise Exception('The two nodes must be with same: manufacturer_id, product_type and product_id')
	for val in source.get_values():
		configuration_value = source.values[val]
		if configuration_value.genre == 'Config':
			if configuration_value.type == 'Button':
				continue
			if configuration_value.is_write_only:
				continue
			target_value = value_utils.get_value_by_index(target_id, COMMAND_CLASS_CONFIGURATION, 1,configuration_value.index)
			if target_value is not None:
				if configuration_value.type == 'List':
					globals.network.manager.setValue(target_value.value_id, configuration_value.data)
					accepted = True
				else:
					accepted = target.set_config_param(configuration_value.index,configuration_value.data)
				if accepted:
					items += 1
					value_utils.mark_pending_change(target_value, configuration_value.data)
	my_result = items != 0
	return utils.format_json_result()

@app.route('/node/<int:node_id>/instance/<int:instance_id>/cc/<int:cc_id>/index/<int:index>/refreshData()', methods=['GET'])
@auth.login_required
def refresh_one_value(node_id, instance_id, index, cc_id):
	utils.check_node_exist(node_id)
	for val in globals.network.nodes[node_id].get_values(class_id=cc_id):
		if globals.network.nodes[node_id].values[val].instance - 1 == instance_id and globals.network.nodes[node_id].values[val].index == index:
			globals.network.nodes[node_id].values[val].refresh()
			return utils.format_json_result()
	raise Exception('This device does not contain the specified value')

@app.route('/node/<int:node_id>/cc/<int:cc_id>/data', methods=['GET'])
@auth.login_required
def get_config(node_id,cc_id):
	utils.check_node_exist(node_id)
	logging.debug("get_config for nodeId:%s" % (node_id,))
	config = {}
	for val in globals.network.nodes[node_id].values:
		list_values = []
		my_value = globals.network.nodes[node_id].values[val]
		if my_value.command_class == cc_id:
			config[globals.network.nodes[node_id].values[val].index] = {}
			if my_value.type == "List" and not my_value.is_read_only:
				result_data = globals.network.manager.getValueListSelectionNum(my_value.value_id)
				values = my_value.data_items
				for index_item, value_item in enumerate(values):
					list_values.append(value_item)
					if value_item == my_value.data_as_string:
						result_data = index_item
			elif my_value.type == "Bool" and not my_value.data:
				result_data = 0
			elif my_value.type == "Bool" and my_value.data:
				result_data = 1
			else:
				result_data = my_value.data
			config[my_value.index]['val'] = {'value2': my_value.data, 'value': result_data,'value3': my_value.label, 'value4': sorted(list_values),'updateTime': int(time.time()), 'invalidateTime': 0}
	return utils.format_json_result(data=config)

@app.route('/node/<int:node_id>/instance/<int:instance_id>/cc/<int:cc_id>/index/<int:index>/setPolling(<int:frequency>)', methods=['GET'])
@auth.login_required
def set_polling_value(node_id, instance_id, cc_id, index, frequency):
	utils.check_node_exist(node_id)
	logging.info('set_polling_value for nodeId: '+str(node_id)+' instance: '+str(instance_id)+' cc : '+str(cc_id)+' index : '+str(index)+' at: '+str(frequency))
	for val in globals.network.nodes[node_id].get_values(class_id=cc_id):
		if globals.network.nodes[node_id].values[val].instance - 1 == instance_id:
			my_value = globals.network.nodes[node_id].values[val]
			if frequency == 0 & my_value.poll_intensity > 0:
				my_value.disable_poll()
			else:
				if globals.network.nodes[node_id].values[val].index == index:
					value_utils.changes_value_polling(frequency, my_value)
				elif my_value.poll_intensity > 0:
						my_value.disable_poll()
	utils.write_config()
	return utils.format_json_result()

@app.route('/node/<int:node_id>/instance/<int:instance_id>/cc/<int:cc_id>/index/<int:index>/button(<action>)', methods=['GET'])
@auth.login_required
def press_button(node_id, instance_id, cc_id, index, action):
	utils.check_node_exist(node_id)
	logging.info('Button nodeId : '+str(node_id)+' instance: '+str(instance_id)+' cc : '+str(cc_id)+' index : '+str(index)+' : ' +str(action))
	for val in globals.network.nodes[node_id].get_values(class_id=cc_id, genre='All', type='All', readonly='All', writeonly='All'):
		if globals.network.nodes[node_id].values[val].instance - 1 == instance_id and globals.network.nodes[node_id].values[val].index == index:
			if action == 'press':
				globals.network.manager.pressButton(globals.network.nodes[node_id].values[val].value_id)
			if action == 'release':
				globals.network.manager.releaseButton(globals.network.nodes[node_id].values[val].value_id)
			return utils.format_json_result()
	return utils.format_json_result(success='error', data='Button not found')

@app.route('/node/<int:node_id>/setRaw(<int:slot_id>,[<value1>,<value2>,<value3>,<value4>,<value5>,<value6>,<value7>,<value8>,<value9>,<value10>])', methods=['GET'])
@auth.login_required
def set_user_code(node_id, slot_id, value1, value2, value3, value4, value5, value6, value7, value8, value9, value10):
	utils.check_node_exist(node_id)
	logging.info("set_user_code2 nodeId:%s slot:%s user code:%s,%s,%s,%s,%s,%s,%s,%s,%s,%s" % (node_id, slot_id, value1, value2, value3, value4, value5, value6, value7, value8, value9, value10,))
	result_value = {}
	for val in globals.network.nodes[node_id].get_values(class_id=COMMAND_CLASS_USER_CODE):
		if globals.network.nodes[node_id].values[val].index == slot_id:
			result_value['data'] = {}
			value = utils.convert_user_code_to_hex(value1) + utils.convert_user_code_to_hex(value2) + utils.convert_user_code_to_hex(value3) + utils.convert_user_code_to_hex(value4) + utils.convert_user_code_to_hex(value5) + utils.convert_user_code_to_hex(value6) + utils.convert_user_code_to_hex(value7) + utils.convert_user_code_to_hex(value8) + utils.convert_user_code_to_hex(value9) + utils.convert_user_code_to_hex(value10)
			original_value = value
			value = binascii.a2b_hex(value)
			globals.network.nodes[node_id].values[val].data = value
			result_value['data'][val] = {'device': node_id, 'slot': slot_id, 'val': original_value}
			return jsonify(result_value)
	return utils.format_json_result()

@app.route('/node/<int:node_id>/instance/0/cc/112/index/0/set(<int:index_id>,<value>,<int:size>)', methods=['GET'])
@auth.login_required
def set_config(node_id, index_id, value, size):
	return utils.format_json_result(data=value_utils.set_config(node_id, index_id, value, size))

@app.route('/node/<int:node_id>/instance/<int:instance_id>/cc/<int:cc_id>/index/<int:index>/set(<value>)', methods=['GET'])
@auth.login_required
def set_value(node_id, instance_id, cc_id, index, value):
	return utils.format_json_result(data=commands.send_command_zwave(node_id, cc_id, instance_id, index, value))

@app.route('/node/<int:node_id>/instance/0/cc/240/index/0/switchAll(<int:state>)', methods=['GET'])
@auth.login_required
def switch_all(node_id, state):
	if state == 0:
		logging.info("SwitchAll Off")
		globals.network.switch_all(False)
	else:
		logging.info("SwitchAll On")
		globals.network.switch_all(True)
	for node_id in globals.network.nodes:
		my_node = globals.network.nodes[node_id]
		if my_node.is_failed:
			continue
		value_ids = my_node.get_switches_all()
		if value_ids is not None and len(value_ids) > 0:
			for value_id in value_ids:
				if my_node.values[value_id].data == "Disabled":
					continue
				elif my_node.values[value_id].data == "On and Off Enabled":
					pass
				if my_node.values[value_id].data == "Off Enabled" and state != 0:
					continue
				if my_node.values[value_id].data == "On Enabled" and state == 0:
					continue
				for switch in my_node.get_switches():
					my_node.values[switch].refresh()
				for dimmer in my_node.get_dimmers():
					my_node.values[dimmer].refresh()
	return utils.format_json_result()	

@app.route('/node/<int:node_id>/<action>(<int:group>,<int:target_id>,<int:instance>)', methods=['GET'])
@auth.login_required
def assoc_action(node_id, group, target_id,instance,action):
	return node_utils.add_assoc(node_id, group, target_id,instance,action)

@app.route('/node/<int:node_id>/setDeviceName(<string:location>,<string:name>,<int:is_enable>)', methods=['GET'])
@auth.login_required
def set_device_name(node_id, location, name, is_enable):
	utils.check_node_exist(node_id)
	logging.info("set_device_name node_id:%s new name ; '%s'. Is enable: %s" % (node_id, name, is_enable,))
	if node_id in globals.disabled_nodes and is_enable:
		globals.disabled_nodes.remove(node_id)
	elif node_id not in globals.disabled_nodes and not is_enable:
		globals.disabled_nodes.append(node_id)
	name = name.encode('utf8')
	name = name.replace('+', ' ')
	globals.network.nodes[node_id].set_field('name', name)
	location = location.encode('utf8')
	location = location.replace('+', ' ')
	globals.network.nodes[node_id].set_field('location', location)
	return utils.format_json_result()