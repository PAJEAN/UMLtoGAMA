# -*- encoding: utf-8 -*-

import re, codecs, json, bs4, warnings, argparse, time
from os import path
from jinja2 import Template
from functools import reduce

# Error and warning codes.
error_codes = {
	'err1': lambda file_path: f'{file_path} not found',
    'err2': lambda tag_name: f'Multiple inheritances detected to {tag_name}',
    'err3': lambda attr_type, tag_name: f'Type {attr_type} unknown to {tag_name}',
    'err4': lambda tag_name: f'Missing type to a {tag_name} attribute',
    'err6': lambda class_name: f'Missing a default value to a static attribute to {class_name}',
    'err7': lambda transition_name: f'Missing condition to {transition_name}',
    'err8': lambda source_id: f'Source id {source_id} not found on state index',
    'err9': lambda: f'Global block must have only one class',
    'err10': lambda instance_id: f'Missing value to instance id {instance_id}',
    'err11': lambda class_id: f'Missing class id {class_id}',
    'err12': lambda attribute_id: f'Missing {attribute_id} attribute during instanciation',
    'err13': lambda: f'Experiment block must have only one class',
    'err14': lambda: f'An instance must have a classifier attribute (type)',
    'err15': lambda class_name: f'{class_name} is not an object or has no name or operation attribute'
}

def raiseException(code, *args):
    raise Exception(error_codes[code](*args))

warning_codes = {
    'warn1': lambda tag_name, attr_name: f'Missing {attr_name} attribute to {tag_name}',
    'warn2': lambda operation_name: f'Multiple return statements detected to {operation_name} operation',
    'warn3': lambda operation_name, parent_name: f'Missing {operation_name} method to {parent_name}',
}

def raiseWarning(code, *args):
    warnings.warn(warning_codes[code](*args))

# Attributes.
def getAttributeValue(root, attribute_name):
    if not root.has_attr(attribute_name):
        raiseWarning('warn1', root['name'], attribute_name)
    return root[attribute_name] if root.has_attr(attribute_name) else None

# Tags.
def extractTag(root, tag_name, attributes = {}):
    return root.find(tag_name, attrs = attributes)

def extractTags(root, tag_name, attributes = {}):
    return root.find_all(tag_name, attrs = attributes)

# Packages.
def extractPackageTag(root, attributes = {}):
    attributes.update({'xsi:type': 'uml:Package'})
    return extractTag(root, 'packagedElement', attributes)

def extractPackageTags(root, attributes = {}):
    attributes.update({'xsi:type': 'uml:Package'})
    return extractTags(root, 'packagedElement', attributes)

# Properties.
def extractProperties(root):
    return {prop['key']: prop['value'] for prop in extractTags(extractTag(root, 'xmi:Extension'), 'details')}

def hasProperty(root, property_name):
    return property_name in extractProperties(root)

# Dependancy link.
def dependancyLink(root):
    return {tag['client']: tag['supplier'] for tag in extractTags(root, 'packagedElement', {'xsi:type': 'uml:Dependency'})}

# Classes.
def extractClasses(root):
    return {tag['xmi:id']: tag for tag in extractTags(root, 'packagedElement', {'xsi:type': 'uml:Class'})}

# Enumerations.
def extractEnumerations(root):
    return {tag['xmi:id']: tag for tag in extractTags(root, 'packagedElement', {'xsi:type': 'uml:Enumeration'})}

# Inheritance class links.
def getParentClassId(root):
    parents = extractTags(root, 'generalization')
    if len(parents) == 1:
        return parents[0]['general']
    elif len(parents) > 0:
        raiseException('err2', root['name']) # Only one possible inheritance.

# Class diagram.
def buildClassDiagram(root, package_name):
    meta_model_package = extractPackageTag(root, {'name': package_name})
    class_tags = extractClasses(meta_model_package)
    enumeration_tags = extractEnumerations(meta_model_package)
    controllers = getControllers(meta_model_package) # Extract FSM.
    dependancy_links = dependancyLink(meta_model_package) # Link between FSM and classes.
    uml_classes = []
    for tag_id in class_tags:
        tag = class_tags[tag_id]
        if not tag.has_attr('isAbstract'): # Don't transfrom abstract classes.
            uml_class = UmlClass(tag)
            uml_class.properties = extractProperties(tag)
            parent_id = getParentClassId(tag)
            if parent_id:
                uml_class.parent = class_tags[parent_id]['name']
            for attribute_tag in extractTags(tag, 'ownedAttribute'): # Attributes.
                attribute = UmlAttribute(attribute_tag)
                attribute.properties = extractProperties(attribute_tag)
                attribute.getHeading()
                attribute.type = getTypeValue(attribute_tag, class_tags, enumeration_tags)
                attribute.is_list = isList(attribute_tag)
                attribute.default_value = getDefaultValue(attribute_tag)
                if attribute.default_value:
                    attribute.default_value = convertDefaultValue(attribute.default_value, attribute.type)
                uml_class.attributes.append(attribute)
            for operation_tag in extractTags(tag, 'ownedOperation'): # Methods.
                operation = UmlOperation(operation_tag)
                operation.properties = extractProperties(operation_tag)
                operation.getHeading()
                return_parameter = extractTags(operation_tag, 'ownedParameter', {'direction': 'return'})
                if len(return_parameter) > 1:
                    raiseWarning('warn2', operation.name)
                elif len(return_parameter) == 1:
                    operation_type = getTypeValue(return_parameter[0], class_tags, enumeration_tags)
                    operation.type = operation_type if operation_type is not None else UmlOperation.gaml_operation_name
                    operation.is_list = isList(return_parameter[0])
                elif operation_tag['name'] != 'init': # Init function doesn't have return.
                    operation.type = UmlOperation.gaml_operation_name
                parameters = extractTags(operation_tag, 'ownedParameter') # Method parameters.
                operation_parameters = []
                for i_param in range(0, len(parameters)):
                    if parameters[i_param].has_attr('name') and (not parameters[i_param].has_attr('direction') or (parameters[i_param].has_attr('direction') and parameters[i_param]['direction'] != 'return')):
                        parameter_name = parameters[i_param]['name']
                        parameter_type = getTypeValue(parameters[i_param], class_tags, enumeration_tags)
                        parameter_is_list = isList(parameters[i_param])
                        operation_parameters.append((f'list<{parameter_type}>' if parameter_is_list else parameter_type, parameter_name))
                operation.getParameters(operation_parameters)
                uml_class.operations.append(operation)
            if tag_id in dependancy_links:
                for state_id in controllers[dependancy_links[tag_id]]:
                    uml_class.controllers.append(controllers[dependancy_links[tag_id]][state_id].translateToGaml())
            uml_class.getHeading()
            uml_class.getType()
            uml_classes.append(uml_class)
    return uml_classes

# Extract behaviors from packages inside meta_model package.
def getControllers(root):
    controller_tags = {tag['xmi:id']: tag for tag in extractPackageTags(root)} # All packages inside meta_model package have to be behaviors and have behavior as property.
    behaviors = {}
    for tag_id in controller_tags:
        tag = controller_tags[tag_id]
        if hasProperty(tag, 'behavior'):
            state_machine = extractTag(tag, 'packagedElement', {'xsi:type': 'uml:StateMachine'}) # Consider only one state machine by package.
            vertex_tags = extractTags(state_machine, 'subvertex')
            states = {}
            for vertex_tag in vertex_tags:
                vertex = UmlState(vertex_tag)
                vertex.getInitialFinal()
                vertex.actions = [key for key in extractProperties(vertex_tag) if key != 'uuid']
                states[vertex.state_id] = vertex
            transitions = extractTags(state_machine, 'transition')
            for transition_tag in transitions:
                if transition_tag['source'] in states and transition_tag['target'] in states:
                    transition = UmlStateTransition(transition_tag)
                    transition.next_state = states[transition_tag['target']].name
                    transition.actions = [key for key in extractProperties(transition_tag) if key != 'uuid']
                    condition = extractTag(extractTag(transition_tag, 'ownedRule', {'xmi:id': transition_tag['guard']}), 'specification')                    
                    if condition:
                        transition.condition = condition['value']
                        states[transition_tag['source']].transitions.append(transition)
                    else:
                        raiseException('err7', transition.name)
                else:
                    raiseException('err8', transition_tag['source'])
            behaviors[tag_id] = states
    return behaviors

# Instanciation.
def instanciation(root, uml_classes):
    instance_tags = extractTags(root, 'packagedElement', {'xsi:type': 'uml:InstanceSpecification'})
    class_attributes = reduce(lambda acc, curr: acc + curr.attributes, uml_classes, []) # Get all attributes from all classes.
    instances = []
    for instance_tag in instance_tags:
        if instance_tag.has_attr('classifier'):
            uml_class = list(filter(lambda uml_class: uml_class.class_id == instance_tag['classifier'], uml_classes)) # Get current class.
            if len(uml_class) == 1:
                instance = GamlInstance()
                uml_class = uml_class[0]
                instance.name = uml_class.name
                instance.properties = extractProperties(instance_tag)
                slot_tags = extractTags(instance_tag, 'slot')
                instance.getHeading()
                for slot_tag in slot_tags:
                    value_tag = extractTag(slot_tag, 'value')
                    if value_tag:
                        attribute_name = list(filter(lambda attribute: attribute.attribute_id == slot_tag['definingFeature'], class_attributes)) # Get current attribute (some attributes can be in mother classes).
                        if len(attribute_name) == 1:
                            attribute_name = attribute_name[0]
                            instance.attributes[attribute_name.name] = value_tag['symbol']
                        else:
                            raiseException('err12', slot_tag['definingFeature'])
                    else:
                        raiseException('err10', slot_tag['xmi:id'])
                instances.append(instance)
            else:
                raiseException('err11', instance_tag['classifier'])
        else:
            raiseException('err14', instance_tag['classifier'])
    instances = sorted(instances, key=lambda instance: float(instance.properties['priority']) if instance.properties and 'priority' in instance.properties else float('inf'))
    return instances

# Get global block.
def getGlobal(root, uml_classes):
    uml_global = buildClassDiagram(root, 'global')
    if len(uml_global) == 1:
        uml_global = GamlGlobal(uml_global[0].attributes, uml_global[0].operations)
        for instance in instanciation(xml_tree, uml_classes):
            uml_global.init.append(instance.translateToGaml())
        uml_global.initCompletion()
        return uml_global
    elif len(uml_global) > 0:
        raiseException('err9')

# Get experiment block.
def getExperiment(root):
    uml_experiment = buildClassDiagram(root, 'experiment')
    if len(uml_experiment) == 1:
        uml_experiment = GamlExperiment(uml_experiment[0].name, uml_experiment[0].attributes, uml_experiment[0].operations, uml_experiment[0].properties)
        uml_experiment.getHeading()
        return uml_experiment
    elif len(uml_experiment) > 0:
        raiseException('err13')

# Type of an attribute or an operation.
def getTypeValue(root, class_tags, enumeration_tags): # Some attributes can have no type.
    if root.has_attr('type'):
        if root['type'] in enumeration_tags:
            return UmlClass.enum_default_type # Enum type.
        elif root['type'] in class_tags:
            return class_tags[root['type']]['name'] # Custom type.
        else:
            raiseException('err3', root['type'], root['name'])
    else:
        type_tag = extractTag(root, 'type')
        if type_tag:
            m = re.match('.*#//(.*)', type_tag['href'])
            if m:
                attribute_type = m.group(1)
                if attribute_type in UmlClass.type_conversion:
                    return UmlClass.type_conversion[attribute_type] # Predefined type.
                else:
                    raiseException('err3', attribute_type, root['name'])
            else:
                raiseException('err4', root['name'])

# Determine if the attribute/operation type/return is a list of primitives/objects or a single value.
def isList(root):
    lower_tag = extractTag(root, 'lowerValue')
    upper_tag = extractTag(root, 'upperValue')
    return True if lower_tag or upper_tag else False # If lowerValue tag or upperValue tag exist, this is a list.
        
# Get default value of an attribute or a reference.
def getDefaultValue(root):
    default_value_tag = extractTag(root, 'defaultValue')
    return default_value_tag['value'] if default_value_tag and default_value_tag.has_attr('value') else None # Avoid to consider nil default value.

# Convert default value to have the good format.
def convertDefaultValue(default_value, value_type):
     # If default_value is a list, brackets [..] have to be precise directly in the model because sometimes default_value is the result of an instruction like "cell where not (each.is_obstacle)".
    if value_type == 'string':
        default_value = '"%s"' % (default_value)
    return default_value

# Skeleton of the json file.
def buildJsonFileSkeleton(*args):

    def extractClass(arg, json_file):
        if isinstance(arg, object) and hasattr(arg, 'operations') and hasattr(arg, 'name'):
            json_file[arg.name] = {}
            for operation in arg.operations:
                json_file[arg.name][operation.name] = ''
        else:
            raiseException('err15', arg)
        return json_file

    json_file = {}
    for arg in args:
        if isinstance(arg, list):
            for el in arg:
                json_file = extractClass(el, json_file)
        else:
            json_file = extractClass(arg, json_file)
    return json_file
    

# State diagram.
class UmlState:
    initial_state_name = 'EntryPoint'
    final_state_name   = 'FinalPoint'

    def __init__(self, root):
        self.state_id = getAttributeValue(root, 'xmi:id')
        self.name = getAttributeValue(root, 'name')
        self.initial = False
        self.final = False
        self.actions = []
        self.transitions = []
    
    def getInitialFinal(self):
        if self.name == UmlState.initial_state_name:
            self.initial = True
        elif self.name == UmlState.final_state_name:
            self.final = True
    
    def translateToGaml(self):
        template = Template('''
    state {{ name }}{% if initial %} initial: true{% elif final %} final: true{% endif %} {
        {% for action in actions %}
        do {{ action }}();
        {% endfor %}
        {% for transition in transitions %}
        {% if transition.actions|length() > 0 %}
        transition to: {{ transition.next_state }} when: {{ transition.condition }} {
        {% for action in transition.actions %}
            do {{ action }}();
        {% endfor %}
        }
        {% else %}
        transition to: {{ transition.next_state }} when: {{ transition.condition }};
        {% endif %}
        {% endfor %}
    }
        ''', trim_blocks=True, lstrip_blocks=True)
        return template.render(**self.__dict__).strip()

class UmlStateTransition:
    def __init__(self, root):
        self.transition_id = getAttributeValue(root, 'xmi:id')
        self.next_state = None
        self.actions = []
        self.condition = None                   

# Uml class.
class UmlClass:
    enum_default_type = 'int'
    type_conversion = {
        'String'        : 'string',
        'Real'          : 'float',
        'Boolean'       : 'bool',
        'Integer'       : 'int'
    }
    object_type = 'object_type'
    protected_facets = ['object_type', 'skills'] # Theses properties are specific during the getHeading() function.

    def __init__(self, root):
        self.class_id = getAttributeValue(root, 'xmi:id')
        self.name = getAttributeValue(root, 'name')
        self.type = None # Specie / grid, etc.
        self.parent = None
        self.attributes = []
        self.operations = []
        self.controllers = []
        self.properties = None
        self.heading = None

    def getHeading(self):
        self.properties.pop('uuid', None) # Clear uuid property.
        headings = ['%s: %s' % (property, self.properties[property]) for property in self.properties if not property in UmlClass.protected_facets]
        if len(self.controllers) > 0:
            headings.append('control: fsm')
        if 'skills' in self.properties:
            headings.append('skills: [%s]' % self.properties['skills'])
        self.heading = ' '.join(headings)

    def getType(self):
        if UmlClass.object_type in self.properties:
            self.type = self.properties[UmlClass.object_type]

    def translateToGaml(self):
        template = Template('''
{% if type %}{{ type }} {% else %}species {% endif %}{{ name }} {% if parent %}parent: {{ parent }} {% endif %}{% if heading %}{{ heading }} {% endif %}{
    {# ---------- Attributes ---------- #}
    {% for attribute in attributes %}
    {% if not attribute.is_static %}
    {{ attribute.translateToGaml() }}
    {% endif %}
    {% endfor %}

    {# ---------- Operations ---------- #}
    {% for operation in operations %}
    {{ operation.translateToGaml() }}
    {% endfor %}

    {# ---------- Controller ---------- #}
    {% for controller in controllers %}
    {{ controller }}
    {% endfor %}
}
        ''', trim_blocks=True, lstrip_blocks=True)
        return template.render(**self.__dict__)

class UmlAttribute:
    def __init__(self, root):
        self.attribute_id = getAttributeValue(root, 'xmi:id')
        self.name = getAttributeValue(root, 'name')
        self.visibility = getAttributeValue(root, 'visibility')
        self.is_static = root.has_attr('isStatic')
        self.type = None
        self.is_list = False
        self.default_value = None
        self.properties = None
        self.heading = None

    def getHeading(self):
        self.heading = ' '.join(['%s: %s' % (key, self.properties[key]) for key in self.properties if key != 'uuid'])

    def translateToGaml(self):
        template = Template('''
    {% if is_list %}
    list<{{ type }}> {{ name }}{% if default_value is string and default_value != '' %} <- {{ default_value }}{% elif default_value is iterable and default_value|length() > 0 %} <- [{{ default_value|join(', ') }}]{% endif %}{% if heading %} {{ heading }}{% endif %};
    {% else %}
    {{ type }} {{ name }}{% if default_value != None %} <- {{ default_value }}{% endif %}{% if heading %} {{ heading }}{% endif %};
    {% endif %}
    ''', trim_blocks=True, lstrip_blocks=True)
        return template.render(**self.__dict__).strip()

class UmlOperation:
    gaml_operation_name = 'action'
    gaml_operations = {}

    def __init__(self, root):
        self.operation_id = getAttributeValue(root, 'xmi:id')
        self.name = getAttributeValue(root, 'name')
        self.content = self.getContent(root)
        self.parameters = None
        self.type = None
        self.is_list = False
        self.properties = None
        self.heading = None
    
    def getHeading(self):
        if 'when' in self.properties:
            self.heading = 'when: %s' % self.properties['when']

    def getParameters(self, parameters):
        if len(parameters) > 0:
            self.parameters = ', '.join(reduce(lambda acc, curr: acc + [f'{curr[0]} {curr[1]}'], parameters, []))

    def getContent(self, root):
        parent_tag_name = getAttributeValue(root.parent, 'name')
        if parent_tag_name in UmlOperation.gaml_operations and self.name in UmlOperation.gaml_operations[parent_tag_name]:
            return UmlOperation.gaml_operations[parent_tag_name][self.name]
        elif len(UmlOperation.gaml_operations) > 0:
            raiseWarning('warn3', self.name, parent_tag_name)
    
    def translateToGaml(self):
        template = Template('''
    {% if name == 'init' %}
    {{ name}} {
    {% elif is_list %}
    list<{{ type }}> {{ name }}{% if parameters %}({{ parameters }}){% endif %}{% if heading %} {{ heading }} {% endif %} {
    {% else %}
    {{ type }} {{ name}}{% if parameters %}({{ parameters }}){% endif %}{% if heading %} {{ heading }} {% endif %} {
    {% endif %}
        {{ content }}
    }
    ''', trim_blocks=True, lstrip_blocks=True)
        return template.render(**self.__dict__).strip()

# Global part of a gaml file.
class GamlGlobal:
    def __init__(self, attributes, operations):
        self.name = 'global'
        self.attributes = attributes
        self.operations = operations
        self.init = []

    def initCompletion(self):
        init_operation = list(filter(lambda operation: operation.name == 'init', self.operations))
        if len(init_operation) == 1:
            self.init = self.init + [init_operation[0].content]

    def translateToGaml(self):
        template = Template('''
global {
    {# ---------- Instanciate all attributes ---------- #}
    {% for attribute in attributes %}
    {% if not attribute.is_static %}
    {{ attribute.translateToGaml() }}
    {% endif %}
    {% endfor %}

    {% if init|length() > 0 %}
    init {
    {% for instance in init %}
        {{ instance }}
    {% endfor %}
    }
    {% endif %}

    {# ---------- Operations ---------- #}
    {% for operation in operations %}
    {% if operation.name != 'init' %}
    {{ operation.translateToGaml() }}
    {% endif %}
    {% endfor %}
}
''', trim_blocks=True, lstrip_blocks=True)
        return template.render(**self.__dict__)

class GamlInstance:
    package_name = 'instanciation'
    protected_facets = ['priority'] # Theses properties are specific during the getHeading() function.

    def __init__(self):
        self.name = None
        self.attributes = {}
        self.properties = None
        self.heading = None
    
    def getHeading(self):
        self.properties.pop('uuid', None) # Clear uuid property.
        headings = ['%s: %s' % (property, self.properties[property]) for property in self.properties if not property in GamlInstance.protected_facets]
        self.heading = ' '.join(headings)

    def translateToGaml(self):
        template = Template('''
        create {{ name }}{% if heading %} {{ heading }}{% endif %} {
            {% for key in attributes %}
            {{ key }} <- {{ attributes[key] }};
            {% endfor %}
        }
        ''', trim_blocks=True, lstrip_blocks=True)
        return template.render(**self.__dict__)

class GamlExperiment:
    def __init__(self, name, attributes, operations, properties):
        self.name = name
        self.attributes = attributes
        self.operations = operations
        self.properties = properties
        self.heading = None

    def getHeading(self):
        if 'type' in self.properties:
            self.heading = 'type: %s' % (self.properties['type'])

    def translateToGaml(self):
        template = Template('''
experiment {{ name }}{% if heading %} {{ heading }} {% endif %} {
    {# ---------- Instanciate all attributes ---------- #}
    {% for attribute in attributes %}
    {% if not attribute.is_static %}
    {% if attribute.is_list %}
    list<{{ attribute.type }}> {{ attribute.name }}{% if attribute.default_value is string and attribute.default_value != '' %} <- {{ attribute.default_value }}{% elif attribute.default_value is iterable and attribute.default_value|length() > 0 %} <- [{{ attribute.default_value|join(', ') }}]{% endif %};
    {% else %}
    {{ attribute.type }} {{ attribute.name }}{% if attribute.default_value != '' %} <- {{ attribute.default_value }}{% endif %};
    {% endif %}
    {% endif %}
    {% endfor %}
    {# ---------- Experience outputs ---------- #}
    {% if operations %}
    output {
    {% for operation in operations %}
        {{ operation.type }} {{ operation.name}} {
            {{ operation.content }}
        }
    {% endfor %}
    }
    {% endif %}
}
''', trim_blocks=True, lstrip_blocks=True)
        return template.render(**self.__dict__)


if __name__== "__main__":
    start_time = time.time()

    parser = argparse.ArgumentParser(description='Parameter --example 1 to run prey/predator or --example 2 to run Luneray\'s flu example.')
    parser.add_argument('--example', type=int, default=1, choices=range(1,3), help='Run an example 1 to run prey/predator and 2 to run Luneray\'s flu.')
    parser.add_argument('-f', '--file', type=str, help='Name of xmi and json files on data/gama and data/models repositories.')
    parser.add_argument('-j', '--json', type=str, help='Build the json file according to the XMI file.')
    args = parser.parse_args()

    if args.file or args.json:
        file_name = args.file if args.file else args.json
        xmi_file_path    = f'data/models/{file_name}.xmi'
        json_file_path   = f'data/gama/{file_name}.json'
        model_name = file_name
    elif args.example == 1:
        xmi_file_path    = 'data/models/preyPredatorGlobal.xmi'
        json_file_path   = 'data/gama/prey_predator_functions.json'
        model_name = 'prey_predator'
    elif args.example == 2:
        xmi_file_path    = 'data/models/lunerayFlu.xmi'
        json_file_path   = 'data/gama/luneray.json'
        model_name = 'luneray_flu'

    if path.exists(xmi_file_path):
        with codecs.open(xmi_file_path, 'r', encoding='utf-8') as fin:
            xml_tree = bs4.BeautifulSoup(fin, 'xml')
    else:
        raiseException('err1', xmi_file_path)
    
    if not args.json:
        if path.exists(json_file_path):
            with codecs.open(json_file_path, 'r', encoding='utf-8') as fin:
                UmlOperation.gaml_operations = json.load(fin)
        else:
            raiseException('err1', json_file_path)

    # Meta model package.
    uml_classes = buildClassDiagram(xml_tree, 'meta_model')
    uml_global = getGlobal(xml_tree, uml_classes)
    uml_experiment = getExperiment(xml_tree)

    if args.json:
        with codecs.open(f'data/gama/{model_name}.json', 'w', encoding='utf-8') as fout:
            json_file = buildJsonFileSkeleton(uml_classes, uml_global, uml_experiment)
            fout.write(json.dumps(json_file, indent=4))
    else:
        output_file_path = 'outputs/gen_src.gaml'
        with codecs.open(output_file_path, 'w', encoding='utf-8') as fout:
            fout.write(f'model {model_name}\n')
            if uml_global:
                fout.write(uml_global.translateToGaml() + '\n')
            if uml_experiment:
                fout.write(uml_experiment.translateToGaml() + '\n')
            for uml_class in uml_classes:
                fout.write(uml_class.translateToGaml() + '\n')
    
    print(f'{model_name} executed in {round(time.time() - start_time, 3)} seconds.')

    