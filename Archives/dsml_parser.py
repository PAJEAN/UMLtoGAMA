# -*- encoding: utf-8 -*-

from abc import ABC, abstractmethod
import re, codecs, json
from os import path
import bs4 
from jinja2 import Template

GLOBAL_TEMPLATE = Template('''
global {
    {% if global_variables %}
    {% for global_variable in global_variables %}
    {{ global_variable }}
    {% endfor %}
    {% endif %}

    {% if init %}
    init {
    {% for i in init %}
        {{ i }}
    {% endfor %}
    }
    {% endif %}
}
''', trim_blocks=True, lstrip_blocks=True)

EXPERIMENT_TEMPLATE = Template('''
experiment {{ experiment_name }} {% if heading %} {{ heading }} {% endif %} {
    {% if global_variables %}
    {% for global_variable in global_variables %}
    {{ global_variable }}
    {% endfor %}
    {% endif %}
    {# ---------- Experience outputs ---------- #}
    {% if output %}
    output {
    {% for i in output %}
        {{ i }}
    {% endfor %}
    }
    {% endif %}
}
''', trim_blocks=True, lstrip_blocks=True)

SPECIE_TEMPLATE = Template('''
{% if not destroy %}
{% if type %}{{ type }} {% else %}species {% endif %} {{ specie_name }} {% if parent_name != '' %} parent: {{ parent_name }} {% endif %} {% if heading %} {{ heading }} {% endif %} {
    {# ---------- Instanciate all attributes ---------- #}
    {% for attribute in attributes %}
    {% if attribute.is_list %}
    list<{{ attribute.type }}> {{ attribute.name }} {% if attribute.value is string and attribute.value != '' %} <- {{ attribute.value }} {% elif attribute.value is iterable and attribute.value|length() > 0 %} <- [{{ attribute.value|join(', ') }}] {% endif %};
    {% else %}
    {{ attribute.type }} {{ attribute.name }} {% if attribute.value != '' %} <- {{ attribute.value }} {% endif %};
    {% endif %}
    {% endfor %}
    {# ---------- Instanciate all attributes ---------- #}
    {% if global_variables %}
    {% for global_variable in global_variables %}
    {{ global_variable }}
    {% endfor %}
    {% endif %}
    {# ---------- Instanciate init part ---------- #}
    {% if init %}
    init {
    {% for i in init %}
        {{ i }}
    {% endfor %}
    }
    {% endif %}
    {# ---------- Instanciate aspects ---------- #}
    {% if aspects %}
    {% for aspect in aspects %}
    aspect {{ aspect.name}} {
        {{ aspect.content }}
    }
    {% endfor %}
    {% endif %}
    {# ---------- Instanciate methods ---------- #}
    {% if methods %}
    {% for method in methods %}
    {{ method.type }} {{ method.name}} {
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
    'EString'       : 'string',
    'String'        : 'string',
    'EFloat'        : 'float',
    'EDouble'       : 'float',
    'EDoubleObject' : 'float',
    'Real'          : 'float',
    'EBoolean'      : 'bool',
    'Boolean'       : 'bool',
    'EBooleanObject': 'bool',
    'EIntegerObject': 'int',
    'Integer'       : 'int',
    'EInt'          : 'int',
    'EDate'         : 'date'
}

TYPE_BLACKLIST = [
    'EJavaObject'
]

ENUM_DEFAULT_TYPE = 'int'

class XmlParser:
    def __init__(self, fname):
        if path.exists(fname):
            with codecs.open(fname, encoding='utf-8') as fp:
                self.tree  = bs4.BeautifulSoup(fp, 'xml')
        else:
            raise ValueError(f'{fname} not found')

    def getTagsFromTagName(self, tag_name):
        tags = []
        for tag in self.tree.find_all(tag_name):
            tags.append(tag)
        return tags

    def getTagsFromAttr(self, tag_name, attr_name, attr_value):
        tags = []
        for tag in self.tree.find_all(tag_name, attrs={attr_name: attr_value}):
            tags.append(tag)
        return tags

"""
    Abstract mother class.
"""
class DsmlParser(ABC):
    def __init__(self, xml_parser, root = None):
        if isinstance(xml_parser, XmlParser):
            self.xml_parser = xml_parser
            self.class_tags = {} # Classes index (by their id/name).
            self.enum_tags  = {} # Enumerations index (by their id/name).
            self.root = root
        else:
            raise TypeError(f'xml_parser has to be a XmlParser object')

    def translateToGaml(self):
        species = []
        if self.root: # Specific species.
            ascendants, descendants = self._getInheritanceLinks()
            specie, seen_tag_ids = self._translateToGamlFromRootedClass(ascendants[self.root], ascendants) # Get ascendants of ROOT element.
            species += specie
            specie, _ = self._translateToGamlFromRootedClass(descendants[self.root] + [self.root], descendants, seen_tag_ids) # Get descendants of ROOT element + ROOT element itself.
            species += specie
        else: # All species.
            species = self._translateAllClassesToGaml(list(self.class_tags.keys()))            
        return species

    def writeIntoFile(self, fname, fmodel, species, other_contents = None):
        with codecs.open(fname, 'w', encoding='utf-8') as fout:
            fout.write(f'model {fmodel}\n\n\n')
            if other_contents:
                fout.write(GLOBAL_TEMPLATE.render(**other_contents['global']) + '\n')
                for experiment in other_contents['experiments']:
                    fout.write(EXPERIMENT_TEMPLATE.render(experiment) + '\n')
            for specie in species:
                fout.write(SPECIE_TEMPLATE.render(**specie) + '\n')

    @abstractmethod
    def _getInheritanceLinks(self): # Get children and parents classes from inheritance links.
        pass

    @abstractmethod
    def _getParentClassName(self, tag): # Get parent class name.
        pass

    @abstractmethod
    def _getTypeOfAttributeOrReference(self, child): # Get type of an attribute or a reference.
        pass

    # Translate one <eClassifiers> EClass.
    def _translateToGamlOneClass(self, current_class):
        if current_class in self.class_tags:
            tag = self.class_tags[current_class] # Extract the tag.
            tag_name = tag['name']
            specie = {'specie_name': tag_name, 'parent_name': '', 'attributes': []}

            if tag.has_attr('eSuperTypes'): # Inheritance.
                specie['parent_name'] = self._getParentClassName(tag)
                if specie['parent_name'] == '':
                    raise ValueError(f'eSuperTypes attribute found but any value extracted to {tag_name}')

            for child in tag.children: # Attributes and references.
                if child.name == 'eStructuralFeatures':
                    attribute = {'e_type': '' , 'type': '', 'is_list': False, 'name': child['name'], 'value': ''}
                    if child['xsi:type'] == 'ecore:EAttribute' or child['xsi:type'] == 'ecore:EReference': # Some attributes have custom type.
                        # Type.
                        variable_type, e_type = self._getTypeOfAttributeOrReference(child)
                        if e_type == '':
                            raise ValueError(f'No eType found to a child of {tag_name}')
                        elif variable_type == 0: # Multiples options because if it's a class we want to add class id into queue and put a type to the enumeration type.
                            attribute['type'] = ENUM_DEFAULT_TYPE
                        elif variable_type == 1:
                            attribute['e_type'] = e_type # It's the index id of the self.class_tags (xmi:id to xmi and name to ecore).
                            attribute['type'] = self.class_tags[e_type]['name']
                        elif variable_type == 2 and e_type in TYPE_CONVERSION:
                            attribute['type'] = TYPE_CONVERSION[e_type]
                        else: # Type not in TYPE_CONVERSION.
                            if e_type in TYPE_BLACKLIST: # Ignore some types.
                                continue
                            raise ValueError(f'Unknown {e_type} eType to {tag_name}')
                        
                        # Default value and Cardinalities.
                        defaultValueLiteral = self._getDefaultValueLiteral(child)
                        if defaultValueLiteral:
                            if variable_type == 0:
                                defaultValueLiteral = self._findIndexValueOnEnum(e_type, defaultValueLiteral)
                            defaultValueLiteral = self._convertDefaultValueLiteral(defaultValueLiteral, attribute['type'])
                        is_list = self._isList(child)
                        attribute['is_list'] = is_list
                        if is_list:
                            attribute['value'] = [defaultValueLiteral] if defaultValueLiteral else []
                        elif defaultValueLiteral:
                            attribute['value'] = defaultValueLiteral

                        # Add attribute to specie.
                        specie['attributes'].append(attribute)
                    else:
                        print('<WARNING> The xsi:type attribute is not known to %s' % (tag['name']))
            return specie
        else:
            raise ValueError(f'{current_class} not found')

    def _translateToGamlFromRootedClass(self, queue, hierarchy, seen_tag_ids = []):
        species = []
        while len(queue) > 0:
            current_class = queue.pop(0)
            if not current_class in seen_tag_ids and not current_class in self.enum_tags:
                seen_tag_ids.append(current_class) # Avoid to loop on multiple references.

                for tag_id in hierarchy[current_class]:
                    queue.append(tag_id)

                specie = self._translateToGamlOneClass(current_class)
                species.append(specie)
                for attribute in specie['attributes']:
                    if attribute['e_type'] != '': # Only custom elements have an e_type defined.
                        queue.append(attribute['e_type'])
        return species, seen_tag_ids

    def _translateAllClassesToGaml(self, queue):
        species = []
        while len(queue) > 0:
            current_class = queue.pop(0)
            if not current_class in self.enum_tags:
                specie = self._translateToGamlOneClass(current_class)
                species.append(specie)
        return species
    
    def _findIndexValueOnEnum(self, enum_key, enum_literal): # Find the index value of an enumeration with the name value.
        index = -1
        if enum_key in self.enum_tags:
            for i, child in enumerate(self.enum_tags[enum_key].children):
                if not isinstance(child, bs4.element.NavigableString) and ((child.has_attr('literal') and child['literal'] == enum_literal) or child['name'] == enum_literal):
                    index = i
                    break
        else:
            raise ValueError(f'{enum_key} not found on index')
        if index == -1:
            raise ValueError(f"{enum_key} doesn't have {enum_literal}")
        return index

    def _getDefaultValueLiteral(self, child): # Get default value of an attribute or a reference.
        defaultValueLiteral = ''
        if child.has_attr('defaultValueLiteral'):
            defaultValueLiteral = child['defaultValueLiteral']
        return defaultValueLiteral
    
    def _convertDefaultValueLiteral(self, defaultValueLiteral, value_type): # /!\ date type.
        if value_type == 'int':
            defaultValueLiteral = int(defaultValueLiteral)
        elif value_type == 'float':
            defaultValueLiteral = float(defaultValueLiteral)
        elif value_type == 'string':
            defaultValueLiteral = '"%s"' % (defaultValueLiteral)
        return defaultValueLiteral

    def _isList(self, child): # Is a list of primitive/object or only one of value.
        is_list = False
        lowerBound = upperBound = None
        if child.has_attr('lowerBound'):
            lowerBound = child['lowerBound']
        if child.has_attr('upperBound'):
            upperBound = child['upperBound']
            
        if lowerBound and upperBound:
            if upperBound == '-1' or int(lowerBound) < int(upperBound):
                is_list = True
            elif lowerBound != upperBound: # So lowerBound > upperBand.
                raise ValueError(f"lowerBound can not be greater than upperBound to {child.parent['name']}")
        elif upperBound:
            if upperBound == '-1' or int(upperBound) > 1:
                is_list = True
            else:
                print(f"<WARNING> upperBound can be equal to 0 or 1 without lowerBound to {child.parent['name']} ?")
        elif lowerBound and lowerBound != '1':
                print(f"<WARNING> lowerBound (={lowerBound}) can be greater than 1 without upperBound to {child.parent['name']} ?")
        return is_list

    def _getChildrenOfATag(self, tag):
        children = []
        for child in tag:
            if not child.name is None:
                children.append(child)
        return children

"""
    Manage ecore file.
"""
class EcoreParser(DsmlParser):
    def __init__(self, xml_parser, root):
        super().__init__(xml_parser, root)
        self.class_tags = {tag['name']: tag for tag in self.xml_parser.getTagsFromTagName('eClassifiers')} # Index classes (by their name).
        self.enum_tags  = {tag['name']: tag for tag in self.xml_parser.getTagsFromAttr('eClassifiers', 'xsi:type', 'ecore:EEnum')} # Index enumerations (by their name).

    def _getInheritanceLinks(self): # Get children and parents classes from inheritance links.
        ascendants = {}
        descendants = {}
        for tag_name in self.class_tags:
            tag = self.class_tags[tag_name]
            if not tag_name in ascendants:
                ascendants[tag_name] = [] # Only one ascendant by eClass.
            if not tag_name in descendants:
                descendants[tag_name] = []
            if tag.has_attr('eSuperTypes'):
                spl = [name.strip() for name in tag['eSuperTypes'].split('#//') if name.strip() != '']
                if len(spl) > 0:
                    for name in spl:
                        ascendants[tag_name].append(name)
                        if not name in descendants:
                            descendants[name] = []
                        descendants[name].append(tag_name)
                else:
                    raise ValueError(f'eSuperTypes declared but without value to {tag_name} tag')
        return ascendants, descendants

    def _getParentClassName(self, tag): # Get parent class name.
        parent = ''
        spl = [s.strip() for s in tag['eSuperTypes'].split('#//') if (s.strip() != '' and s.strip() != self.root)] # Echap ROOT tag (hack to found right classes).
        if len(spl) == 1: # Only one possible inheritance.
            parent = spl[0] # Parent name.
        elif len(spl) > 1:
            raise ValueError(f"Multiple inheritances detected to {tag['name']} tag")
        return parent

    def _getTypeOfAttributeOrReference(self, child): # Get type of an attribute or a reference.
        e_type = ''; variable_type = 0
        m = re.match('^#//(.*)', child['eType'])
        if m: # Custom type.
            if m.group(1) in self.enum_tags:
                e_type = m.group(1)
                variable_type = 0 # Enum type.
            else:
                e_type = m.group(1)
                variable_type = 1 # Custom Type.
        else: # Predefined type.
            spl = child['eType'].split('/')
            if len(spl) > 1:
                e_type = spl[-1]
                variable_type = 2 # Predefined type.
        return variable_type, e_type

"""
    Manage xmi file.
"""
class XmiParser(DsmlParser):
    def __init__(self, xml_parser, root):
        super().__init__(xml_parser, root)
        self.class_tags = {tag['xmi:id']: tag for tag in self.xml_parser.getTagsFromTagName('eClassifiers')} # Index classes (by their id).
        self.enum_tags  = {tag['xmi:id']: tag for tag in self.xml_parser.getTagsFromAttr('eClassifiers', 'xsi:type', 'ecore:EEnum')} # Index enumerations (by their id).

    def _getInheritanceLinks(self): # Get children and parents classes from inheritance links for all nodes.
        ascendants = {}
        descendants = {}
        for tag_id in self.class_tags:
            tag = self.class_tags[tag_id]
            if not tag_id in ascendants:
                ascendants[tag_id] = [] # Only one ascendant by eClass.
            if not tag_id in descendants:
                descendants[tag_id] = []
            if tag.has_attr('eSuperTypes'):
                parent_ids = re.findall('_[A-Za-z0-9]*', tag['eSuperTypes'])
                if len(parent_ids) > 0:
                    if len(parent_ids) == 1:
                        parent_id = parent_ids[0]
                        if parent_id in self.class_tags:
                            ascendants[tag_id].append(parent_id)
                            if not parent_id in descendants:
                                descendants[parent_id] = []
                            descendants[parent_id].append(tag_id)
                        else:
                            raise ValueError(f'ID {parent_id} not found')
                    else:
                        raise ValueError(f'Multiples inheritance detected')
                else:
                    raise ValueError(f'eSuperTypes declared but without value to {tag_id} tag')
        return ascendants, descendants

    def _getParentClassName(self, tag): # Get parent class name.
        parent = ''
        parent_ids = re.findall('_[A-Za-z0-9]*', tag['eSuperTypes'])
        if len(parent_ids) == 1: # Only one possible inheritance.
            parent_id = parent_ids[0] # Parent name.
            if parent_id in self.class_tags:
                parent = self.class_tags[parent_id]['name']
            else:
                raise ValueError(f'{parent_id} not found')
        elif len(parent_ids) > 1:
            raise ValueError(f"Multiple inheritances detected to {tag['name']} tag")
        return parent

    def _getTypeOfAttributeOrReference(self, child): # Get type of an attribute or a reference.
        e_type = ''; variable_type = 0; e_type_label = 'eType'
        if not child.has_attr('eType'): # eStructuralFeatures can display their eType in a child.
            children = self._getChildrenOfATag(child)
            if len(children) == 1:
                child = children[0]
                e_type_label = 'href'
            else:
                print(f"<WARNING> An eStructuralFeatures can have 0 or more than one child ?")
        m = re.match('^(_[A-Za-z0-9]*)', child[e_type_label])
        if m: # Custom type (xmi file).
            if m.group(1) in self.enum_tags:
                e_type = m.group(1)
                variable_type = 0 # Enum type.
            elif m.group(1) in self.class_tags:
                e_type = m.group(1)
                variable_type = 1 # Custom Type.
            else:
                raise ValueError(f'{m.group(1)} not found')
        else: # Predefined type.
            spl = child[e_type_label].split('/')
            if len(spl) > 1:
                e_type = spl[-1]
                variable_type = 2 # Predefined type.
        return variable_type, e_type

"""
    Manage UML file to build a finite state machine.
"""
class FsmFromUml:
    def __init__(self, xml_parser):
        if isinstance(xml_parser, XmlParser):
            self.xml_parser = xml_parser
            self.states = {tag['xmi:id']: tag for tag in self.xml_parser.getTagsFromAttr('packagedElement', 'xsi:type', 'uml:Class')} # A state is represented by an uml class.
            self.edges  = {tag['xmi:id']: tag for tag in self.xml_parser.getTagsFromAttr('packagedElement', 'xsi:type', 'uml:Dependency')} # An edge is represented by an uml dependency link.
            self.edges_condition = {tag['xmi:id']: tag for tag in self.xml_parser.getTagsFromTagName('ownedComment')} # Transition conditions is a comment attached to a uml dependency link (indexed by the id of the tag).
            if len(list(self.edges_condition.keys())) != len(list(self.edges.keys())):
                raise TypeError(f'The number of edges has to be equal to the number of condition')    
        else:
            raise TypeError(f'xml_parser has to be a XmlParser object')

    def buildFsm(self): # Create all states about FSM.
        states = []
        transitions = self._getTransition()
        for state_id in self.states:
            state = {
                'name': '',
                'initial': False,
                'final': False,
                'functions': [],
                'transitions': []
            }
            state['name'] = self.states[state_id]['name']

            if state['name'] == 'enterState':
                state['initial'] = True
            elif state['name'] == 'exitState':
                state['final'] = True

            # Get functions to run at the state.
            functions = self.states[state_id].find_all('ownedAttribute')
            if len(functions) > 0:
                for function in functions:
                    if function.has_attr('name'):
                        state['functions'].append(function['name'])
                    else:
                        raise ValueError(f'No name attribute for an ownedAttribute to {state_id} tag')
            
            if state_id in transitions:
                for transition in transitions[state_id]:
                    target_name = self.states[transition['target']]['name']

                    state['transitions'].append({
                        'next_state': target_name,
                        'action': None if transition['name'] == 'None' else transition['name'],
                        'condition': transition['condition']
                    })
            states.append(state)

        return states
        
    def _getTransition(self):
        # Get conditions.
        conditions = {}
        for comment_id in self.edges_condition:
            if self.edges_condition[comment_id].has_attr('annotatedElement') and self.edges_condition[comment_id].has_attr('body'):
                conditions[self.edges_condition[comment_id]['annotatedElement']] = self.edges_condition[comment_id]['body'] # annotatedElement is the id of the edge element (uml:Dependency).
            else:
                raise ValueError(f'Missing attributes to {comment_id} tag')
        transition_direction = {}
        # Get direction (origin to target).
        for edge_id in self.edges:
            if self.edges[edge_id].has_attr('client') and self.edges[edge_id].has_attr('supplier') and self.edges[edge_id].has_attr('name'): # Indexed by the origin state.
                client = self.edges[edge_id]['client']
                supplier = self.edges[edge_id]['supplier']
                if not client in transition_direction:
                    transition_direction[client] = []
                transition_direction[client].append({'name': self.edges[edge_id]['name'], 'target': supplier, 'condition': conditions[edge_id]})
            else:
                raise ValueError(f'Missing attributes to {edge_id} tag')
        return transition_direction

"""
    Parse JSON file with complementary informations like variable instanciation.
"""
class GamlComplementaryInformations:

    def __init__(self, json_file):
        self.json_file = json.load(json_file)

    def fillSpecies(self, species, models = {}): # Information about specie and other class type (e.g. grid).
        for specie in species:
            specie_name = specie['specie_name']
            if specie_name in self.json_file:
                if 'type' in self.json_file[specie_name]:
                    specie['type'] = self.json_file[specie_name]['type']
                if 'aspects' in self.json_file[specie_name]:
                    specie['aspects'] = []
                    for aspect_id in self.json_file[specie_name]['aspects']:
                        specie['aspects'].append({
                            'name': aspect_id,
                            'content': self.json_file[specie_name]['aspects'][aspect_id]
                        })
                if 'methods' in self.json_file[specie_name]:
                    specie['methods'] = []
                    for method_id in self.json_file[specie_name]['methods']:
                        specie['methods'].append({
                            'name': method_id,
                            'type': self.json_file[specie_name]['methods'][method_id]['type'],
                            'content': self.json_file[specie_name]['methods'][method_id]['content']
                        })
                if 'local_variables' in self.json_file[specie_name]:
                    if 'attributes' in specie:
                        for attribute in specie['attributes']:
                            if attribute['name'] in self.json_file[specie_name]['local_variables']:
                                attribute['value'] = self.json_file[specie_name]['local_variables'][attribute['name']]
                    else:
                        raise ValueError(f'Missing attributes to {specie_name} specie')
                if 'global_variables' in self.json_file[specie_name]:
                    specie['global_variables'] = self.json_file[specie_name]['global_variables']
                if 'init' in self.json_file[specie_name]:
                    specie['init'] = self.json_file[specie_name]['init']
                if 'fsm' in self.json_file[specie_name]:
                    specie['fsm'] = True
                    if specie_name in models and 'heading' in self.json_file[specie_name]:
                        specie['fsm'] = models[specie_name]
                    else:
                        raise ValueError(f'Missing model to {specie_name} specie')
                if 'heading' in self.json_file[specie_name]:
                    specie['heading'] = self.json_file[specie_name]['heading']
                if 'destroy' in self.json_file[specie_name]:
                    specie['destroy'] = self.json_file[specie_name]['destroy']        
        return species

    def fillGlobal(self):
        global_content = {}
        if 'global' in self.json_file:
            global_content['global_variables'] = self.json_file['global']['global_variables']
            global_content['init'] = self.json_file['global']['init']
        return global_content
    
    def fillExperiment(self):
        experiments = None
        if 'experiments' in self.json_file:
            experiments = self.json_file['experiments']
        return experiments

"""
    Main part.
"""
if __name__== "__main__":
    
    def ecoreParserTest():
        ROOT = 'NamedObjectWithOperationalSemanticDescription'
        xml_parser = XmlParser('data/models/resiist.ecore')
        translator = EcoreParser(xml_parser, ROOT)
        species = translator.translateToGaml()
        translator.writeIntoFile('outputs/gen_src.gaml', 'resiist', species)

    def xmiParserTest(is_rooted):
        ROOT = None
        if is_rooted:
            ROOT = '_HVp3AILeEeqWAK1R3DAmBw106'
        xml_parser = XmlParser('data/models/RESIIST.xmi')
        translator = XmiParser(xml_parser, ROOT)
        species = translator.translateToGaml()
        translator.writeIntoFile('outputs/gen_src.gaml', 'resiist', species)

    def globalTransformation():
        ROOT = None
        # Get classes.
        xml_parser = XmlParser('data/models/predator_prey.ecore')
        translator = EcoreParser(xml_parser, ROOT)
        species = translator.translateToGaml()

        # UML to FSM.
        models = {}
        models['generic_species'] = []
        xml_parser = XmlParser('data/models/preyPredator.xmi')
        fsmFromUml = FsmFromUml(xml_parser)
        states = fsmFromUml.buildFsm()
        for state in states:
            models['generic_species'].append(FSM_STATE_TEMPLATE.render(**state))

        # JSON to Gaml initialisation.
        with codecs.open('data/gama/prey_predator_info.json', 'r', encoding='utf-8') as fin:
            gaml_info = GamlComplementaryInformations(fin)
        species = gaml_info.fillSpecies(species, models)
        other_contents = {}
        other_contents['global'] = gaml_info.fillGlobal()
        other_contents['experiments'] = gaml_info.fillExperiment()

        # Write result in a file.
        translator.writeIntoFile('outputs/gen_src.gaml', 'prey_predator', species, other_contents)
    
    globalTransformation()

    """
    ToDo:
    + Réaliser des fichiers pour tester les différentes fonctions de test.
    + Harmoniser le fichier JSON pour considérer l'instanciation des variables correctement, ce qui veut dire pouvoir renseigner dans les species l'ensemble des attributs (notamment ceux hérités).
    + Diagramme fonction.
    """