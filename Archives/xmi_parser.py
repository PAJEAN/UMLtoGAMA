# -*- encoding: utf-8 -*-

import re, codecs
from os import path
import bs4 
from jinja2 import Template

SPECIE_TEMPLATE = Template('''
species {{ specie_name }} {%- if parent_name != '' %} parent: {{ parent_name }} {%- endif %} {
    {%- for attribute in attributes %}
    {%- if not attribute.value is string and attribute.value is iterable %}
    list<{{ attribute.type }}> {{ attribute.name }} {%- if attribute.value|length() > 0 %} <- [{{ attribute.value|join(', ') }}] {%- endif %};
    {%- else %}
    {{ attribute.type }} {{ attribute.name }} {%- if attribute.value != '' %} <- {{ attribute.value }} {%- endif %};
    {%- endif %}
    {%- endfor %}
}
''')
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
    'EDate'         : 'date'
}

TYPE_BLACKLIST = [
    'EJavaObject'
]
ROOT = 'ResiistStakeholder'
ENUM_DEFAULT_TYPE = 'int'

class EcoreParser:
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


class EcoreToGaml:
    def __init__(self, classes, enumerations):
        if isinstance(classes, list) and isinstance(enumerations, list):
            self.classes = classes # List of eClass tags.
            self.enumerations = enumerations # List of EEnum tags (set of values).
            self.class_index = {tag['name']: tag for tag in self.classes} # Index classes by their name.
            self.class_id_index = {tag['xmi:id']: tag for tag in self.classes} # Index classes by their id.
            self.enum_index  = {tag['name']: tag for tag in self.enumerations} # Index enumerations by their name.
            self.enum_id_index = {tag['xmi:id']: tag for tag in self.enumerations} # Index enumerations by their id.
        else:
            raise TypeError(f'classes and enumerations have to be lists')

    def translate(self):
        ascendants, descendants = self._getInheritanceLinks()
        species = []

        for i in range(2):
            seen_tag_names = [] # Keep trace of seen tag names.
            queue = [ROOT]
            while len(queue) > 0:
                current_class = queue.pop(0)
                if not current_class in seen_tag_names and not current_class in self.enum_index:
                    seen_tag_names.append(current_class) # Avoid to loop on multiple references.

                    if i % 2 == 0:
                        for ascendant in ascendants[current_class]: # Get ascendants of ROOT element.
                            queue.append(ascendant)
                    else:
                        for descendant in descendants[current_class]: # Get descendants of ROOT element.
                            queue.append(descendant)

                    if current_class in self.class_index:
                        tag = self.class_index[current_class] # Extract the tag.
                        tag_name = tag['name']
                        specie = {'specie_name': current_class, 'parent_name': '', 'attributes': []}

                        if tag.has_attr('eSuperTypes'): # Inheritance.
                            specie['parent_name'] = self.getParentClass(tag)
                            # print(self.getParentClass(tag))
                            if specie['parent_name'] == '':
                                raise ValueError(f'eSuperTypes attribute found but any value extracted to {tag_name}')

                        for child in tag.children: # Attributes and references.
                            if child.name == 'eStructuralFeatures':
                                attribute = {'type': '', 'name': child['name'], 'value': ''}
                                if child['xsi:type'] == 'ecore:EAttribute' or child['xsi:type'] == 'ecore:EReference': # Some attributes have custom type.
                                    # Type.
                                    variable_type, e_type = self.getTypeOfAttributeOrReference(child)
                                    if e_type == '':
                                        raise ValueError(f'No eType found to a child of {tag_name}')
                                    elif variable_type == 0:
                                        attribute['type'] = ENUM_DEFAULT_TYPE
                                    elif variable_type == 1:
                                        queue.append(e_type) # Add to queue to build corresponding specie.
                                        attribute['type'] = e_type
                                    elif variable_type == 2 and e_type in TYPE_CONVERSION:
                                        attribute['type'] = TYPE_CONVERSION[e_type]
                                    else: # Type not in TYPE_CONVERSION.
                                        if e_type in TYPE_BLACKLIST: # Ignore some types.
                                            continue
                                        raise ValueError(f'Unknown {e_type} eType to {tag_name}')
                                    
                                    # Default value and Cardinalities.
                                    defaultValueLiteral = self.getDefaultValueLiteral(child)
                                    if defaultValueLiteral:
                                        if variable_type == 0:
                                            defaultValueLiteral = self.findIndexValueOnEnum(e_type, defaultValueLiteral)
                                        defaultValueLiteral = self.convertDefaultValueLiteral(defaultValueLiteral, attribute['type'])
                                    is_list = self.isList(child)
                                    if is_list:
                                        attribute['value'] = [defaultValueLiteral] if defaultValueLiteral else []
                                    elif defaultValueLiteral:
                                        attribute['value'] = defaultValueLiteral

                                    # Add attribute to specie.
                                    specie['attributes'].append(attribute)
                                else:
                                    print('<WARNING> The xsi:type attribute is not known to %s' % (tag['name']))
                        species.append(specie)
                    else:
                        raise ValueError(f'{current_class} not found')
        return species

    def _getInheritanceLinks(self): # Get children and parents classes from inheritance links.
        ascendants = {}
        descendants = {}
        for tag in self.classes:
            tag_name = tag['name']
            if not tag_name in ascendants:
                ascendants[tag_name] = [] # Only one ascendant by eClass.
            if not tag_name in descendants:
                descendants[tag_name] = []
            if tag.has_attr('eSuperTypes'):
                # spl = [name.strip() for name in tag['eSuperTypes'].split('#//') if name.strip() != '']
                # if len(spl) > 0:
                #     for name in spl:
                #         ascendants[tag_name].append(name)
                #         if not name in descendants:
                #             descendants[name] = []
                #         descendants[name].append(tag_name)
                parent_ids = re.findall('_[A-Za-z0-9]*', tag['eSuperTypes'])
                if len(parent_ids) > 0:
                    if len(parent_ids) == 1:
                        name = parent_ids[0]
                        if name in self.class_id_index:
                            name = self.class_id_index[name]['name']
                            ascendants[tag_name].append(name)
                            if not name in descendants:
                                descendants[name] = []
                            descendants[name].append(tag_name)
                        else:
                            raise ValueError(f'ID {name} not found on class_id_index')
                    else:
                        raise ValueError(f'<WARNING> Multiples inheritance detected')
                else:
                    raise ValueError(f'eSuperTypes declared but without value to {tag_name} tag')
        return ascendants, descendants
    
    def findIndexValueOnEnum(self, enum_name, enum_literal):
        index = -1
        if enum_name in self.enum_index:
            for i, child in enumerate(self.enum_index[enum_name].children):
                if not isinstance(child, bs4.element.NavigableString) and ((child.has_attr('literal') and child['literal'] == enum_literal) or child['name'] == enum_literal):
                    index = i
                    break
        else:
            raise ValueError(f'{enum_name} not found on index')
        if index == -1:
            raise ValueError(f"{enum_name} doesn't have {enum_literal}")
        return index

    def getParentClass(self, tag): # Get parent class name.
        parent = ''
        # spl = [s.strip() for s in tag['eSuperTypes'].split('#//') if (s.strip() != '' and s.strip() != ROOT)] # Echap ROOT tag (hack to found good classes).
        # if len(spl) == 1: # Only one possible inheritance.
        #     parent = spl[0] # Parent name.
        # elif len(spl) > 1:
        #     raise ValueError(f"Multiple inheritances detected to {tag['name']} tag")

        parent_ids = re.findall('_[A-Za-z0-9]*', tag['eSuperTypes'])

        if len(parent_ids) == 1: # Only one possible inheritance.
            parent = parent_ids[0] # Parent name.
            if parent in self.class_id_index:
                parent = self.class_id_index[parent]['name']
            else:
                raise ValueError(f'{parent} not found on class_id_index')
        elif len(parent_ids) > 1:
            raise ValueError(f"Multiple inheritances detected to {tag['name']} tag")
        return parent

    def getTypeOfAttributeOrReference(self, child): # Get type of an attribute or a reference.
        e_type = ''; variable_type = 0; e_type_label = 'eType'
        if not child.has_attr('eType'): # eStructuralFeatures can display their eType in a child.
            children = self.getChildrenOfATag(child)
            if len(children) == 1:
                child = children[0]
                e_type_label = 'href'
            else:
                print(f"<WARNING> An eStructuralFeatures can have more than one child ?")
        # m = re.match('^#//(.*)', child[e_type_label])
        # if m: # Custom type (ecore file).
        #     if m.group(1) in self.enum_index:
        #         e_type = m.group(1)
        #         variable_type = 0 # Enum type.
        #     else:
        #         e_type = m.group(1)
        #         variable_type = 1 # Custom Type.
        m = re.match('^(_[A-Za-z0-9]*)', child[e_type_label])
        if m: # Custom type (xmi file).
            if m.group(1) in self.enum_id_index:
                e_type = self.enum_id_index[m.group(1)]['name']
                variable_type = 0 # Enum type.
            elif m.group(1) in self.class_id_index:
                e_type = self.class_id_index[m.group(1)]['name']
                variable_type = 1 # Custom Type.
            else:
                raise ValueError(f'{m.group(1)} not found on indexes')
        else: # Predefined type.
            spl = child[e_type_label].split('/')
            if len(spl) > 1:
                e_type = spl[-1]
                variable_type = 2 # Predefined type.


        return variable_type, e_type

    def getChildrenOfATag(self, tag):
        children = []
        for child in tag:
            if not child.name is None:
                children.append(child)
        return children

    def getDefaultValueLiteral(self, child): # Get default value of an attribute or a reference.
        defaultValueLiteral = ''
        if child.has_attr('defaultValueLiteral'):
            defaultValueLiteral = child['defaultValueLiteral']
        return defaultValueLiteral
    
    def convertDefaultValueLiteral(self, defaultValueLiteral, value_type): # /!\ date type.
        if value_type == 'int':
            defaultValueLiteral = int(defaultValueLiteral)
        elif value_type == 'float':
            defaultValueLiteral = float(defaultValueLiteral)
        elif value_type == 'string':
            defaultValueLiteral = '"%s"' % (defaultValueLiteral)
        return defaultValueLiteral

    def isList(self, child): # Is a list of primitive/object or only one of value.
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

    def writeIntoFile(self, fname, fmodel, species):
        with codecs.open(fname, 'w', encoding='utf-8') as fout:
            fout.write(f'model {fmodel}\n\n\n')
            fout.write('global {}\n\n')
            for specie in species:
                fout.write(SPECIE_TEMPLATE.render(**specie) + '\n')


if __name__== "__main__":
    ecore_tree = EcoreParser('data/RESIIST.xmi')
    translator = EcoreToGaml(ecore_tree.getTagsFromTagName('eClassifiers'), ecore_tree.getTagsFromAttr('eClassifiers', 'xsi:type', 'ecore:EEnum'))
    species = translator.translate()
    translator.writeIntoFile('gen_src.gaml', 'ecoreToGaml', species)

