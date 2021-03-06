# -*- coding:utf-8 -*-
from django.utils.translation import ugettext_lazy as _
import slugify
from django.db import models
# from django.db.models import CharField
from rdfalchemy import rdfSubject, rdfSingle
import rdflib
from django.conf import settings
from django_extensions.db import fields as exfields
from urlparse import urlsplit
from import_rdf.models import EntrySite
from djrdf.tools import uri_to_json
from django.contrib.sites.models import Site
import urllib
import logging
import shortuuid


# Serializer
rdflib.plugin.register('json-ld', rdflib.plugin.Serializer,
        'rdflib_jsonld.jsonld_serializer', 'JsonLDSerializer')

log = logging.getLogger('djrdf')


# A class where every common methods are stored
# Be aware that in case od an no imported object (from an rdfStore)
# the triple (obj, rdf:type, type) has to be store by hand
# Example 
# mrdf = myRdfSubject()
# mrdf.db.add(mrdf, settings.NS.rdf.type, mrdf.rdf_type)
class myRdfSubject(rdfSubject):
    dct_created = rdfSingle(settings.NS.dct.created)
    dct_modified = rdfSingle(settings.NS.dct.modified)


    # The _remove method deletes all the triples which
    # have  self.resUri as subject of the triple
    # _remove is a rdfSubject method
    def remove(self):
        try:
            self.delete()
        except Exception:
            pass
        self._remove(self.db, cascade='all', objectCascade=True)

    @property
    def uri_import(self):
        return u"http://%s/get_rdf/?url=%s" % (\
            Site.objects.get_current().domain,
            urllib.quote_plus(self.uri)
            )

    @property
    def authority_source(self):
        scheme, host, path, query, fragment = urlsplit(self.uri)
        try:
            es = EntrySite.objects.get(home="%s://%s" % (scheme, host))
        except EntrySite.DoesNotExist:
            return host
        return es.label



    @classmethod
    def importFromEntries(cls):
        """ Import all resources with rdf_type cls.rdf_type from all sites
            This method would be used only to rebuild the rdf store
        """
        for es in EntrySite.objects.all():
            print """
            Importation of rdf data from %s
            """ % es.label
            # Contexts seem to be useless
            es.toSesameRep(settings.SESAME_REPOSITORY_NAME, es.sparql(), None, cls.rdf_type, force=True)




# The "joint" class. This class is only used in a multiple heritage context :
# - One class derived from rdfSubject (over classes by sesame.myRdfSubject class) 
# - and the djRdf class which subclasses the Django Model class
#
# Warning : deleting a rdfSubject using myRdfSubject.remove() 
# will also call the delete() method of the django Model class
class djRdf(models.Model):
    # TODO : ces deux champs doivent disparaitre.... cela casse la logique
    # rdf. Ils ne sont la  que pour nourrir les feeds. Charcher comment remplir 
    # le feeds a l'aide query sparql
    created = exfields.CreationDateTimeField(_(u'created'), null=True)
    modified = exfields.ModificationDateTimeField(_(u'modified'), null=True)
    uri = models.CharField(max_length=250)

    uri_data_name = 'default'

    @property
    def uuid(self):
        scheme, host, path, query, fragment = urlsplit(self.uri)
        sp = path.split('/')
        return sp[len(sp) - 2]




    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        # print "ENTER INIT with %s and %s" % (args, kwargs)
        # import pdb; pdb.set_trace();
        if args != ():
            # As the objects inherits from differents classes
            # We have to discard the args in order to prepare the calls
            # of the superclass methods

            # TODO C'est pas fini..... On perd trop de trucs

            if kwargs == {}:
                kwargs['id'] = None
                kwargs['uri'] = None
                a0 = args[0]
                lf = self.__class__._meta.local_fields
                n = len(lf)
                 # In this case the args are a rows from the django database
                if isinstance(a0, int):
                    if (len(args) == n):
                        for i in range(n):
                            kwargs[lf[i].name] = args[i]
                    else:
                        raise Exception(_(u'Unhandled call for object %s with args %s and kwargs') % (self, args, kwargs))
                # Here the instance is created using the methods of rdfSubject
                else:
                    if isinstance(a0, rdfSubject):
                        kwargs['uri'] = a0.resUri
                    elif isinstance(a0, rdflib.term.URIRef):
                        kwargs['uri'] = a0
                    else:
                        raise Exception(_(u'Unhandled call for object %s with args %s and kwargs') % (self, args, kwargs))
                    # We have to make the links with the django objects, if it exists
                    try:
                        o = self.__class__.objects.get(uri=unicode(kwargs['uri']))
                        # id and uri are already set
                        kwargs['id'] = o.id
                        for i in range(2, n):
                            kwargs[lf[i].name] = o.__dict__[lf[i].name]
                    except self.__class__.DoesNotExist:
                        # Nothing to do.... wait for a save for example
                        pass
            else:
                raise Exception(_(u'Unhandled call for object %s with args %s and kwargs') % (self, args, kwargs))
        # print "ARGs %s and %s" % (args, kwargs)
        super(djRdf, self).__init__(**kwargs)
        # oui car la methode __init__ de Model appelle cette de rdfSubject et crée un blank node
        if 'uri' in kwargs:
            self.resUri = rdflib.term.URIRef(kwargs['uri'])

    def __repr__(self):
        """ To be compliante with the rdfSubject representation """
        return "%s('%s')" % (self.__class__.__name__, self.n3())

    def __str__(self):
        return unicode(self.resUri)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self._get_pk_val() == other._get_pk_val() and self.uri == other.uri

    # TODO : It is possible that we have to set all "rdfalchemy" fields
    # to None so that they are re-initialized
    def save(self, *args, **kwargs):
        self.resUri = rdflib.term.URIRef(self.uri)
        # USELESS?????
        # if self.uri != '':
        #     # It is important, if the resource is created in django ORM
        #     # first and if the uri does not exists before
        self.db.add((self, settings.NS.rdf.type, self.rdf_type))
        # Call the "real" save() method.
        super(djRdf, self).save(*args, **kwargs)


    def toJson(self):
        return uri_to_json(self.uri, self.db)

    @staticmethod
    def cleanAllDjRdfmodels(model=None):
        """  Clean ALL djangoRdf models. 
             To be used ONLY to rebuild the all rdf data
        """
        if model == None:
            for m in models.get_models():
                if djRdf in m.__mro__:
                    for o in m.objects.all():
                        o.delete()
        else:
            for o in model.objects.all():
                o.delete()

    @classmethod
    def create_uri(cls, label=None):
        host = "http://%s/id/%s/" % (Site.objects.get_current().domain, cls.uri_data_name) 
        if not label:
            return host + '%s/' % shortuuid.uuid()
        else:
            return host + '%s/' % slugify.slugify(label)



from django.core.signals import  request_finished
from djrdf.signals import post_save_callback
request_finished.connect(post_save_callback, sender=djRdf)



