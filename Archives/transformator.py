# -*- encoding: utf-8 -*-

import re, codecs, json
from os import path
import bs4 
from jinja2 import Template

GLOBAL_TEMPLATE = Template('''
global {
    {# ---------- Instanciate all attributes ---------- #}
    {% for attribute in attributes %}
    {% if attribute.is_list %}
    list<{{ attribute.type }}> {{ attribute.name }}{% if attribute.default_value is string and attribute.default_value != '' %} <- {{ attribute.default_value }}{% elif attribute.default_value is iterable and attribute.default_value|length() > 0 %} <- [{{ attribute.default_value|join(', ') }}]{% endif %};
    {% else %}
    {{ attribute.type }} {{ attribute.name }}{% if attribute.default_value != '' %} <- {{ attribute.default_value }}{% endif %};
    {% endif %}
    {% endfor %}

    {% if init_block %}
    init {
    {% for init in init_block %}
        {{ init }}
    {% endfor %}
    }
    {% endif %}
}
''', trim_blocks=True, lstrip_blocks=True)

EXPERIMENT_TEMPLATE = Template('''
experiment {{ name }}{% if heading %} {{ heading }} {% endif %} {
    {# ---------- Instanciate all attributes ---------- #}
    {% for attribute in attributes %}
    {% if attribute.is_list %}
    list<{{ attribute.type }}> {{ attribute.name }}{% if attribute.default_value is string and attribute.default_value != '' %} <- {{ attribute.default_value }}{% elif attribute.default_value is iterable and attribute.default_value|length() > 0 %} <- [{{ attribute.default_value|join(', ') }}]{% endif %};
    {% else %}
    {{ attribute.type }} {{ attribute.name }}{% if attribute.default_value != '' %} <- {{ attribute.default_value }}{% endif %};
    {% endif %}
    {% endfor %}
    {# ---------- Experience outputs ---------- #}
    {% if methods %}
    output {
    {% for method in methods %}
        {{ method.type }} {{ method.name}} {
            {{ method.content }}
        }
    {% endfor %}
    }
    {% endif %}
}
''', trim_blocks=True, lstrip_blocks=True)

CREATE_INIT_TEMPLATE = Template('''
        create {{ name }} {
            {# ---------- Instanciate all attributes ---------- #}
            {% for attribute in attributes %}
            {{ attribute.name }} <- {{ attribute.value }};
            {% endfor %}
        }
''', trim_blocks=True, lstrip_blocks=True)

SPECIE_TEMPLATE = Template('''
{% if not destroy %}
{% if type %}{{ type }} {% else %}species {% endif %}{{ name }} {% if parent_name != '' %}parent: {{ parent_name }} {% endif %}{% if heading %}{{ heading }} {% endif %}{
    {# ---------- Instanciate all attributes ---------- #}
    {% for attribute in attributes %}
    {% if attribute.is_list %}
    list<{{ attribute.type }}> {{ attribute.name }}{% if attribute.default_value is string and attribute.default_value != '' %} <- {{ attribute.default_value }}{% elif attribute.default_value is iterable and attribute.default_value|length() > 0 %} <- [{{ attribute.default_value|join(', ') }}]{% endif %} {{ attribute.heading }};
    {% else %}
    {{ attribute.type }} {{ attribute.name }}{% if attribute.default_value != '' %} <- {{ attribute.default_value }}{% endif %} {{ attribute.heading }};
    {% endif %}
    {% endfor %}

    {# ---------- Instanciate methods ---------- #}
    {% if methods %}
    {% for method in methods %}
    {% if method.name == 'init' %}
    {{ method.name}} {
    {% elif method.is_list %}
    list<{{ method.type }}> {{ method.name}} {
    {% else %}
    {{ method.type }} {{ method.name}} {
    {% endif %}
        {{ method.content }}
    }
    {% endfor %}
    {% endif %}
    {# ---------- Instanciate controller ---------- #}
    {% if fsm %}
    {% for state in fsm %}
    {{ state }}
    {% endfor %}
    {% endif %}
}
{% endif %}
''', trim_blocks=True, lstrip_blocks=True)


FSM_STATE_TEMPLATE = Template('''
    state {{ name }} {% if initial %} initial: true {% elif final %} final: true {% endif %} {
        {% for function in functions %}
        do {{ function }}();
        {% endfor %}
        {% for transition in transitions %}
        {% if transition.action %}
        transition to: {{ transition.next_state }} when: {{ transition.condition }} {
            do {{ transition.action }}();
        }
        {% else %}
        transition to: {{ transition.next_state }} when: {{ transition.condition }};
        {% endif %}
        {% endfor %}
    }
''', trim_blocks=True, lstrip_blocks=True)

TYPE_CONVERSION = { # From .ecore to Gaml.
    'String'        : 'string',
    'Real'          : 'float',
    'Boolean'       : 'bool',
    'Integer'       : 'int'
}

ENUM_DEFAULT_TYPE = 'int' # Enum are just simple arrays.

class XmlParser:
    def __init__(self, fname):
        if path.exists(fname):
            with codecs.open(fname, encoding='utf-8') as fp:
                self.tree = bs4.BeautifulSoup(fp, 'xml')
        else:
            raise ValueError(f'{fname} not found')

class Transformator:
    def __init__(self, xml_parser):
        self.xml_parser = xml_parser
        self.meta_model_object = MetaModel(xml_parser.tree.find('packagedElement', attrs = {'xsi:type': 'uml:Package', 'name': 'meta_model'}))
        self.gaml_global = MetaModel(xml_parser.tree.find('packagedElement', attrs={'xsi:type': 'uml:Package', 'name': 'global'}))
        self.gaml_experiment = MetaModel(xml_parser.tree.find('packagedElement', attrs={'xsi:type': 'uml:Package', 'name': 'experiment'}))
        self.gaml_instances = xml_parser.tree.find_all('packagedElement', attrs={'xsi:type': 'uml:InstanceSpecification'})

    def translateToGaml(self):
        species = self.meta_model_object.translateToGaml()
        gaml_global = self.gaml_global.translateToGaml()
        if len(gaml_global) == 1:
            gaml_global = gaml_global[0]
            instances = []
            for tag in self.gaml_instances:
                instances.append(self._instanciation(tag))
            gaml_global['init_block'] = []
            for instance in instances:
                gaml_global['init_block'].append(CREATE_INIT_TEMPLATE.render(**instance))
        elif len(gaml_global) > 0:
            raise ValueError(f'Global block must have only one class')
        gaml_experiment = self.gaml_experiment.translateToGaml()
        if len(gaml_experiment) == 1:
            gaml_experiment = gaml_experiment[0]
        elif len(gaml_experiment) > 0:
            raise ValueError(f'Experiment block must have only one class')
        

        return species, gaml_global, gaml_experiment
    
    def _instanciation(self, tag):
        instance = {
            'name': self.xml_parser.tree.find(attrs = {'xmi:id': tag['classifier']})['name'], # Name of the instanciated specie.
            'attributes': [] # Attributes of the instanciated specie.
        }
        slot_tags = tag.find_all('slot')
        for slot_tag in slot_tags:
            value_tag = slot_tag.find('value')
            if value_tag:
                instance['attributes'].append({
                    'name': self.xml_parser.tree.find(attrs = {'xmi:id': slot_tag['definingFeature']})['name'],
                    'value': value_tag['symbol']
                })
            else:
                instance_id = slot_tag['xmi:id']
                raise ValueError(f'Missing value to instance id {instance_id}')
        return instance

    def writeIntoFile(self, fname, fmodel, species, gaml_global = None, gaml_experiment = None):
        with codecs.open(fname, 'w', encoding='utf-8') as fout:
            fout.write(f'model {fmodel}\n\n\n')
            if gaml_global:
                fout.write(GLOBAL_TEMPLATE.render(**gaml_global) + '\n')
            if gaml_experiment:
                fout.write(EXPERIMENT_TEMPLATE.render(gaml_experiment) + '\n')
            for specie in species:
                fout.write(SPECIE_TEMPLATE.render(**specie) + '\n')

class MetaModel:
    def __init__(self, meta_model_tags):
        self.meta_model_tags = meta_model_tags
        self.class_tags = {tag['xmi:id']: tag for tag in self.meta_model_tags.find_all('packagedElement', attrs={'xsi:type': 'uml:Class'})}
        self.enum_tags = {tag['xmi:id']: tag for tag in self.meta_model_tags.find_all('packagedElement', attrs={'xsi:type': 'uml:Enumeration'})}

    def _getBehavior(self):
        # All packages inside meta_model package have to be behaviors and have behavior as property.
        behaviors_tags = {tag['xmi:id']: tag for tag in self.meta_model_tags.find_all('packagedElement', attrs={'xsi:type': 'uml:Package'})}
        behaviors = {}
        for tag_id in behaviors_tags:
            tag = behaviors_tags[tag_id]
            behavior_properties = tag.find('xmi:Extension').find('details', attrs={'key': 'behavior'}) # Filter package inside meta-model to select behaviors.
            if behavior_properties:
                state_machine = tag.find_all('packagedElement', attrs={'xsi:type': 'uml:StateMachine'})
                if len(state_machine) == 1:
                    vertices = state_machine[0].find_all('subvertex')
                    states = {}
                    for vertex in vertices:
                        vertex_id = vertex['xmi:id']
                        states[vertex_id] = {
                            'name': vertex['name'],
                            'initial': False,
                            'final': False,
                            'functions': [],
                            'transitions': []
                        }
                        if vertex['name'] == 'EntryPoint':
                            states[vertex_id]['initial'] = True
                        elif vertex['name'] == 'FinalPoint':
                            states[vertex_id]['final'] = True

                        function_properties = vertex.find('xmi:Extension').find_all('details')
                        states[vertex_id]['functions'] = [funct['key'] for funct in function_properties if funct['key'] != 'uuid']

                    transitions = state_machine[0].find_all('transition')
                    for transition_tag in transitions:
                        if transition_tag['source'] in states and transition_tag['target'] in states:
                            transition = {
                                    'next_state': states[transition_tag['target']]['name'],
                                    'action': '', # Not implemented yet.
                                    'condition': ''
                            }
                            condition = transition_tag.find('ownedRule', attrs={'xmi:id': transition_tag['guard']}).find('specification') # Condition.
                            if condition:
                                transition['condition'] = condition['value']
                                states[transition_tag['source']]['transitions'].append(transition)
                            else:
                                raise ValueError(f'Condition not find')
                        else:
                            raise ValueError(f'Source id not found on states')
                    behaviors[tag_id] = states.copy()
                else:
                    print('<WARNING> A state machine can have more than one package element ?')
        return behaviors

    def _linkDependancy(self):
        return {tag['client']: tag['supplier'] for tag in self.meta_model_tags.find_all('packagedElement', attrs={'xsi:type': 'uml:Dependency'})} # Class to a package.

    def _getParentClassName(self, tag): # Get parent class name.
        parent_tag_id = ''
        parents = tag.find_all('generalization')
        if len(parents) == 1: # Only one possible inheritance.
            parent_tag_id = parents[0]['general'] # Parent tag id.
        elif len(parents) > 0:
            tag_name = tag['name']
            raise ValueError(f'Multiple inheritances detected to {tag_name} tag')
        return parent_tag_id

    def _getTypeOfAttributeOrReference(self, tag): # Get type of an attribute or a reference.
        attribute_type = ''
        variable_type = -1 # To differenciate custom, enum and predefined types.
        if tag.has_attr('type'): # Custom type.
            attribute_type = tag['type']
            if tag['type'] in self.enum_tags:
                variable_type = 0 # Enum type.
            else:
                variable_type = 1 # Custom Type.
        else:
            type_tag = tag.find('type')
            if type_tag:
                m = re.match('.*#//(.*)', type_tag['href'])
                if m:
                    attribute_type = m.group(1)
                    variable_type = 2 # Predefined type.
                else:
                    tag_name = tag['name']
                    raise ValueError(f'Missing type to {tag_name} tag')
        return variable_type, attribute_type

    def _getTypeName(self, variable_type, attribute_type):
        return_type_name = ''
        # if attribute_type == '': # Distinguish custom, enumeration and predefined types.
        #     raise ValueError(f'Missing attribute type for a {tag_name} attribute')
        if variable_type == -1:
            return_type_name = '' # Some attribute in Gama are 
        elif variable_type == 0: # Enum.
            return_type_name = ENUM_DEFAULT_TYPE
        elif variable_type == 1: # Custom.
            return_type_name = self.class_tags[attribute_type]['name']
        elif variable_type == 2 and attribute_type in TYPE_CONVERSION:
            return_type_name = TYPE_CONVERSION[attribute_type] # Predefinied type.
        else: # Type not in TYPE_CONVERSION.
            raise ValueError(f'Unknown {attribute_type} attribute type for a {tag_name} attribute')
        return return_type_name

    def _getDefaultValueLiteral(self, tag): # Get default value of an attribute or a reference.
        default_value = ''
        default_value_tag = tag.find('defaultValue')
        if default_value_tag and default_value_tag.has_attr('value'): # Avoid to consider nil default value.
            default_value = default_value_tag['value']
        return default_value

    def _convertDefaultValueLiteral(self, default_value, value_type):
        if value_type == 'string':
            default_value = '"%s"' % (default_value)
        return default_value
    
    def _isList(self, tag): # Is a list of primitive/object or only one of value.
        is_list = False
        parent_name = tag.parent['name']
        lower_bound = upper_bound = None
        lower_bound_tag = tag.find('lowerValue')
        upper_bound_tag = tag.find('upperValue')
        if lower_bound_tag:
            lower_bound = lower_bound_tag['value'] if lower_bound_tag.has_attr('value') else 0
        if upper_bound_tag:
            upper_bound = upper_bound_tag['value'] if upper_bound_tag.has_attr('value') else '*'
        if lower_bound and upper_bound:
            if upper_bound == '*' or int(lower_bound) < int(upper_bound):
                is_list = True
            elif lower_bound != upper_bound: # So lowerBound > upperBand.
                raise ValueError(f'lowerValue can not be greater than upperValue to {parent_name}')
        elif upper_bound:
            if upper_bound == '*' or int(upper_bound) > 1:
                is_list = True
            else:
                print(f"<WARNING> upperValue can be equal to 0 or 1 without lowerValue to {parent_name} ?")
        elif lower_bound and lower_bound != '1':
                print(f"<WARNING> lowerValue (={lower_bound}) can be greater than 1 without upperValue to {parent_name} ?")
        return is_list

    def _heading(self, heading):
        heading_text = ''
        # Grid.
        if 'width' in heading and 'height' in heading and 'neighbors' in heading:
            if heading['width'] and heading['height'] and heading['neighbors']:
                heading_text = 'width: %s height: %s neighbors: %s' % (heading['width'], heading['height'], heading['neighbors'])
            else:
                raise ValueError(f'Missing default value to static attribute grid')
        elif 'type' in heading:
            if heading['type']:
                heading_text = 'type: %s' % (heading['type'])
            else:
                raise ValueError(f'Missing default value to static attribute experiment type')
        return heading_text

    def _methods(self, tag, tag_parent):
        if GAMA_BANK:
            with codecs.open(GAMA_BANK, 'r', encoding='utf-8') as fin:
                methods_content = json.load(fin)
            tag_name = tag['name']
            if tag_parent in methods_content and tag_name in methods_content[tag_parent]:
                methods = {
                    'type': '', # Return type.
                    'is_list': False, # If return is a list of type.
                    'name': tag_name, # Name of the method.
                    'content': methods_content[tag_parent][tag_name] # Content of the method.
                }
                return_parameter = tag.find('ownedParameter')
                if return_parameter:
                    variable_type, return_type = self._getTypeOfAttributeOrReference(return_parameter)
                    methods['type'] = self._getTypeName(variable_type, return_type)
                    methods['is_list'] = self._isList(return_parameter)
                else:
                    if tag_name != 'init': # Init function doesn't return.
                        methods['type'] = 'action'
                return methods
            else:
                raise ValueError(f'Method {tag_name} not found to {tag_parent}')
        
    def translateToGaml(self):
        classes = []
        behaviors = self._getBehavior()
        dependancy_links = self._linkDependancy()
        for tag_id in self.class_tags:
            if not tag_id in self.enum_tags:
                tag = self.class_tags[tag_id] # Extract the tag.
                if not tag.has_attr('isAbstract'):
                    tag_name = tag['name']
                    one_class = { # Init.
                        'id': tag_id, # Id in XMI file.
                        'type': '', # species, grid, etc.
                        'name': tag_name, # Class name.
                        'parent_name': '', # Inheritance.
                        'heading': '', # To indicate behaviors (control, skills).
                        'attributes': [], # Attributes and their default value.
                        'methods': [], # Methods of the class.
                        'fsm': [] # Controller of the agent.
                    }
                    # --- Inheritance --- #
                    parent_id = self._getParentClassName(tag)
                    if parent_id != '':
                        if parent_id in self.class_tags:
                            one_class['parent_name'] = self.class_tags[parent_id]['name']
                        else:
                            raise ValueError(f'{parent_id} id not found')
                    # --- Attributes --- #
                    for child in tag.find_all('ownedAttribute', isStatic=False): # Attributes and references.
                        attribute = {
                            'type': '', # Attribute type.
                            'is_list': False, # Cardinality of the attribute (0..1, 0..*, etc.).
                            'name': child['name'], # Name of the attribute.
                            'default_value': '', # Default value of the attribute.
                            'heading': '' # Gaml enables to add some update information about attribute like update and max keywords.
                        }
                        # Heading.
                        properties = child.find('xmi:Extension').find_all('details')
                        attribute['heading'] = ' '.join(['%s: %s' % (prop['key'], prop['value']) for prop in properties if prop['key'] != 'uuid'])
                        # Attribute type.
                        variable_type, attribute_type = self._getTypeOfAttributeOrReference(child)
                        attribute['type'] = self._getTypeName(variable_type, attribute_type)
                        # Attribute default value and cardinality.
                        default_value = self._getDefaultValueLiteral(child)
                        if default_value: # Enum default value has to be a int.
                            attribute['default_value'] = self._convertDefaultValueLiteral(default_value, attribute['type'])
                        is_list = self._isList(child)
                        attribute['is_list'] = is_list
                        if is_list:
                            attribute['default_value'] = [attribute['default_value']] if default_value != '' else []
                        # Adding attribute to one_class.
                        one_class['attributes'].append(attribute)
                    # --- Heading --- #
                    static_attributes = tag.find_all('ownedAttribute', isStatic=True)
                    if len(static_attributes) > 0:
                        heading = {}
                        for private_attribute in static_attributes:
                            if private_attribute['name'] == 'object_type':
                                one_class['type'] = self._getDefaultValueLiteral(private_attribute)
                            else:
                                heading[private_attribute['name']] = self._getDefaultValueLiteral(private_attribute)
                        heading = self._heading(heading)
                        one_class['heading'] = heading
                     # --- Controller --- #
                    if tag_id in dependancy_links:
                        if one_class['heading'] != '':
                            one_class['heading'] += ' '
                        one_class['heading'] += 'control: fsm'
                        for state_id in behaviors[dependancy_links[tag_id]]:
                            one_class['fsm'].append(FSM_STATE_TEMPLATE.render(**behaviors[dependancy_links[tag_id]][state_id]))
                    # --- Type and methods --- #
                    for child in tag.find_all('ownedOperation'): # Methods.
                        one_class['methods'].append(self._methods(child, tag_name))
                    classes.append(one_class)
        return classes

    


if __name__== "__main__":
    GAMA_BANK = 'data/gama/prey_predator_functions.json'

    def globalTransformation():
        xml_parser = XmlParser('data/models/preyPredatorGlobal.xmi')
        transformator = Transformator(xml_parser)
        species, gaml_global, gaml_experiment = transformator.translateToGaml()
        transformator.writeIntoFile('outputs/gen_src.gaml', 'prey_predator', species, gaml_global, gaml_experiment)
    
    globalTransformation()