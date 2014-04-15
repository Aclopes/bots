#!/usr/bin/env python
''' Start bots-engine.'''
import sys
import os
import atexit
import logging
#~ import socket
from django.utils.translation import ugettext as _
#bots-modules
import botslib
import botsglobal
import botsinit
#~ import cleanup

def abspathdata(filename):
    ''' abspathdata if filename incl dir: return absolute path; else (only filename): return absolute path (datadir)'''
    if '/' in filename: #if filename already contains path
        return botslib.join(filename)
    else:
        #~ directory = botsglobal.ini.get('directories','data')
        return botslib.join(data_storage,filename)
botslib.abspathdata = abspathdata

def start():
    ''' sysexit codes:
        0: OK, no errors
        1: (system) errors incl parsing of command line arguments
        2: bots ran OK, but there are errors/process errors  in the run
        3: Database is locked, but "maxruntime" has not been exceeded.
    '''
    #NOTE: bots directory should always be on PYTHONPATH - otherwise it will not start.
    #********command line arguments**************************
    usage = '''
    This is "%(name)s" version %(version)s, part of Bots open source edi translator (http://bots.sourceforge.net).
    Does the actual translations and communications; it's the workhorse. It does not have a fancy interface.

    Usage:
        %(name)s  [config-option]
    Config-option:
        -c<directory>        directory for configuration files (default: config).

    '''%{'name':os.path.basename(sys.argv[0]),'version':botsglobal.version}
    configdir = 'config'
    for arg in sys.argv[1:]:
        if arg.startswith('-c'):
            configdir = arg[2:]
            if not configdir:
                print 'Error: configuration directory indicated, but no directory name.'
                sys.exit(1)
        elif arg in ["?", "/?",'-h', '--help'] or arg.startswith('-'):
            print usage
            sys.exit(0)
    #***********end handling command line arguments**************************
    
    botsinit.generalinit(configdir)     #find locating of bots, configfiles, init paths etc.
    #set working directory to bots installation. advantage: when using relative paths it is clear that this point paths within bots installation. 
    os.chdir(botsglobal.ini.get('directories','botspath'))

    #**************initialise logging******************************
    process_name = 'engine2'
    botsglobal.logger = botsinit.initenginelogging(process_name)
    atexit.register(logging.shutdown)
    for key,value in botslib.botsinfo():    #log info about environement, versions, etc
        botsglobal.logger.info(u'%(key)s: "%(value)s".',{'key':key,'value':value})

    #**************connect to database**********************************
    try:
        botsinit.connect()
    except Exception,msg:
        botsglobal.logger.exception(_(u'Could not connect to database. Database settings are in bots/config/settings.py. Error: "%(msg)s".'),{'msg':msg})
        sys.exit(1)
    else:
        botsglobal.logger.info(_(u'Connected to database.'))
        atexit.register(botsglobal.db.close)

        
    try:
        userscript,scriptname = botslib.botsimport('routescripts','botsengine')
    except ImportError:      #userscript is not there; other errors like syntax errors are not catched
        userscript = scriptname = None
    #***acceptance tests: initialiase acceptance user script******************************
    acceptance_userscript = acceptance_scriptname = None
    if botsglobal.ini.getboolean('acceptance','runacceptancetest',False):
        botsglobal.logger.info(_(u'This run is an acceptance test - as indicated in option "runacceptancetest" in bots.ini.'))
        try:
            acceptance_userscript,acceptance_scriptname = botslib.botsimport('routescripts','bots_acceptancetest')
        except ImportError:
            botsglobal.logger.info(_(u'In acceptance test there is no script file "bots_acceptancetest.py" to check the results of the acceptance test.'))

    try:
        #~ botslib.prepare_confirmrules()
        #in acceptance tests: run a user script before running eg to clean output directories******************************
        botslib.tryrunscript(acceptance_userscript,acceptance_scriptname,'pretest')
        botslib.tryrunscript(userscript,scriptname,'pre')
        errorinrun = engine2_run()
    except Exception,msg:
        botsglobal.logger.exception(_(u'Severe error in bots system:\n%(msg)s'),{'msg':str(msg)})    #of course this 'should' not happen.
        sys.exit(1)
    else:
        if errorinrun:
            sys.exit(2) #indicate: error(s) in run(s)
        else:
            sys.exit(0) #OK



import glob
import shutil
import inmessage
import outmessage
import transform
import datetime
import envelope
try:
    import cElementTree as ET
except ImportError:
    try:
        import elementtree.ElementTree as ET
    except ImportError:
        try:
            from xml.etree import cElementTree as ET
        except ImportError:
            from xml.etree import ElementTree as ET
from botsconfig import *

'''
information in:
- infile:
    - path
    - filename (suited for globbing)
- translate:
    (like translate table)
- outfile:
    - path
    - filename   #including * and  {}options

information out:
- infile: path, error
- outfile: path, editype, messagetype, frompartner, topartner, [infile path (list)]

Translation:
list of dicts.

'''
data_storage = 'botssys/data2'


class Run(object):
    inpath = None
    outpath = None
    incoming = []  #as received
    translated = [] #result of translations
    outgoing = []  #as enveloped & outgoing
    errorinrun = 0

def engine2_run():
    botslib.dirshouldbethere(data_storage)
    
    run = get_control_information()
    read_incoming(run)
    translate(run)
    mergemessages(run)
    write_outgoing(run)
    trace(run)
    report(run)
    cleanup(run)
    return run.errorinrun


def get_control_information():
    run = Run()
    run.inpath = 'botssys/infile/edifact_xml/xml'
    run.infilename = '*'
    run.outpath = 'botssys/outfile'
    run.outfilename = '{editype}_{infile:name}_{datetime:%Y%m%d}_*.edi'
    run.translation = dict(editype='xml',messagetype = 'invoice')
    return run

def read_incoming(run):
    outputdir = botslib.join(run.inpath,run.infilename)
    filelist = [filename for filename in glob.iglob(outputdir) if os.path.isfile(filename)]
    filelist.sort()
    for infilename in filelist:
        try:
            filename = transform.unique('bots_file_name')
            abs_filename = botslib.abspathdata(filename)
            shutil.copy(infilename,abs_filename)          #move if to be delted
        except:
            txt = botslib.txtexc()
            run.incoming.append({'infilename':infilename,'filename':filename,'error':txt})
        else:
            run.incoming.append({'infilename':infilename,'filename':filename,'error':''})
                
def translate(run):
    for messagedict in run.incoming:
        try:
            #read whole edi-file: read, parse and made into a inmessage-object. Message is represented as a tree (inmessage.root is the root of the tree).
            edifile = inmessage.parse_edi_file(frompartner='',
                                                topartner='',
                                                filename=messagedict['filename'],
                                                messagetype=run.translation['messagetype'],
                                                testindicator='',
                                                editype=run.translation['editype'],
                                                charset='',
                                                alt='',
                                                fromchannel='',
                                                idroute='',
                                                command='')
            edifile.checkforerrorlist() #no exception if infile has been lexed and parsed OK else raises an error
            #~ print 'parsed file',messagedict['internal_in_filename']

            #~ if int(routedict['translateind']) == 3: #parse & passthrough; file is parsed, partners are known, no mapping, does confirm. 
                #~ raise botslib.GotoException('dummy')
            #~ continue    #file is parsed; no errors. no translation
            
            #edifile.ta_info contains info about incoming file: QUERIES, charset etc
            for inn_splitup in edifile.nextmessage():   #splitup messages in parsed edifile
                try:
                    #inn_splitup.ta_info: parameters from inmessage.parse_edi_file(), syntax-information and parse-information
                    number_of_loops_with_same_alt = 0
                    while 1:    #continue as long as there are (alt-)translations
                        #lookup the translation************************
                        #~ tscript,toeditype,tomessagetype = 'invoice_xml2edifact' ,'edifact','INVOICD96AUNEAN008'
                        tscript,toeditype,tomessagetype = botslib.lookup_translation(fromeditype=inn_splitup.ta_info['editype'],
                                                                            frommessagetype=inn_splitup.ta_info['messagetype'],
                                                                            frompartner=inn_splitup.ta_info['frompartner'],
                                                                            topartner=inn_splitup.ta_info['topartner'],
                                                                            alt=inn_splitup.ta_info['alt'])
                            
                        #run mapping script************************
                        filename_translated = transform.unique('bots_file_name')
                        #~ print 'outfile',filename_translated
                        out_translated = outmessage.outmessage_init(editype=toeditype,
                                                                    messagetype=tomessagetype,
                                                                    filename=filename_translated,
                                                                    reference=transform.unique('messagecounter'),
                                                                    statust=OK,
                                                                    divtext=tscript)    #make outmessage object
                        
                        #~ botsglobal.logger.debug(_(u'Mappingscript "%(tscript)s" translates messagetype "%(messagetype)s" to messagetype "%(tomessagetype)s".'),
                                                #~ {'tscript':tscript,'messagetype':inn_splitup.ta_info['messagetype'],'tomessagetype':out_translated.ta_info['messagetype']})
                        translationscript,scriptfilename = botslib.botsimport('mappings',inn_splitup.ta_info['editype'],tscript)    #import mappingscript
                        alt_from_previous_run = inn_splitup.ta_info['alt']      #needed to check for infinite loop
                        doalttranslation = botslib.runscript(translationscript,scriptfilename,'main',inn=inn_splitup,out=out_translated)
                        botsglobal.logger.debug(_(u'Mappingscript "%(tscript)s" finished.'),{'tscript':tscript})
                        
                        #manipulate for some attributes after mapping script
                        if 'topartner' not in out_translated.ta_info:    #out_translated does not contain values from run......
                            out_translated.ta_info['topartner'] = inn_splitup.ta_info['topartner']
                        if 'botskey' in inn_splitup.ta_info:
                            inn_splitup.ta_info['reference'] = inn_splitup.ta_info['botskey']
                        if 'botskey' in out_translated.ta_info:    #out_translated does not contain values from run......
                            out_translated.ta_info['reference'] = out_translated.ta_info['botskey']
                            
                        #check the value received from the mappingscript to determine what to do in this while-loop. Handling of chained trasnlations.
                        if doalttranslation is None:    
                            #translation(s) are done; handle out-message 
                            out_translated.writeall()   #write result of translation.
                            #make translated record (if all is OK)
                            translated_dict = inn_splitup.ta_info.copy()
                            translated_dict.update(out_translated.ta_info)
                            translated_dict.update(messagedict)
                            run.translated.append(translated_dict)
                            del out_translated
                            break   #break out of while loop
                        elif isinstance(doalttranslation,dict):
                            #some extended cases; a dict is returned that contains 'instructions' for some type of chained translations
                            if 'type' not in doalttranslation or 'alt' not in doalttranslation:
                                raise botslib.BotsError(_(u"Mappingscript returned '%(alt)s'. This dict should not have 'type' and 'alt'."),{'alt':doalttranslation})
                            if alt_from_previous_run == doalttranslation['alt']:
                                number_of_loops_with_same_alt += 1
                            else:
                                number_of_loops_with_same_alt = 0
                            if doalttranslation['type'] == u'out_as_inn':
                                #do chained translation: use the out-object as inn-object, new out-object
                                #use case: detected error in incoming file; use out-object to generate warning email
                                handle_out_message(out_translated,ta_translated)
                                inn_splitup = out_translated    #out-object is now inn-object
                                if isinstance(inn_splitup,outmessage.fixed):    #for fixed: strip all values in node
                                    inn_splitup.root.stripnode()
                                inn_splitup.ta_info['alt'] = doalttranslation['alt']   #get the alt-value for the next chained translation
                                if not 'frompartner' in inn_splitup.ta_info:
                                    inn_splitup.ta_info['frompartner'] = ''
                                if not 'topartner' in inn_splitup.ta_info:
                                    inn_splitup.ta_info['topartner'] = ''
                                inn_splitup.ta_info.pop('statust')
                            elif doalttranslation['type'] == u'no_check_on_infinite_loop':
                                #do chained translation: allow many loops wit hsame alt-value.
                                #mapping script will have to handle this correctly.
                                number_of_loops_with_same_alt = 0
                                handle_out_message(out_translated,ta_translated)
                                del out_translated
                                inn_splitup.ta_info['alt'] = doalttranslation['alt']   #get the alt-value for the next chained translation
                            else:   #there is nothing else
                                raise botslib.BotsError(_(u'Mappingscript returned dict with an unknown "type": "%(doalttranslation)s".'),{'doalttranslation':doalttranslation})
                        else:  #note: this includes alt '' (empty string)
                            if alt_from_previous_run == doalttranslation:
                                number_of_loops_with_same_alt += 1
                            else:
                                number_of_loops_with_same_alt = 0
                            #do normal chained translation: same inn-object, new out-object
                            out_translated.writeall()
                            del out_translated
                            inn_splitup.ta_info['alt'] = doalttranslation   #get the alt-value for the next chained translation
                        if number_of_loops_with_same_alt > 10:
                            raise botslib.BotsError(_(u'Mappingscript returns same alt value over and over again (infinite loop?). Alt: "%(doalttranslation)s".'),{'doalttranslation':doalttranslation})
                    #end of while-loop (trans**********************************************************************************
                #exceptions file_out-level: exception in mappingscript or writing of out-file
                except:
                    #2 modes: either every error leads to skipping of  whole infile (old  mode) or errors in mappingscript/outfile only affect that branche
                    txt = botslib.txtexc()
                    print txt
                    messagedict['error'] += txt.strip()
                else:
                    pass
                    #~ print 'succes'
        #exceptions file_in-level
        except botslib.GotoException:   #edi-file is OK, file is passed-through after parsing.
            #~ edifile.handleconfirm(ta_fromfile,error=False)
            #~ botsglobal.logger.debug(_(u'Parse & passthrough for input file "%(filename)s".'),row)
            txt = botslib.txtexc()
            print txt
        except:
            txt = botslib.txtexc()
            messagedict['error'] += txt.strip()
            #~ edifile.handleconfirm(ta_fromfile,error=True)
            #~ botsglobal.logger.debug(u'Error in translating input file "%(filename)s":\n%(msg)s',{'filename':row['filename'],'msg':txt})
        else:
            pass

            
def mergemessages(run):
    names_envelope_criteria = ('editype','messagetype','frompartner','topartner','testindicator','charset','contenttype','envelope','rsrv3')
    merge_yes = {}
    merge_no = []       #can be non-unique: as a list
    #walk over run.translated; sort by envelope-criteria in 2 dicts
    for translated in run.translated:
        filename = translated.get('filename')
        infilename = translated.get('infilename')
        nrmessages = translated.get('nrmessages')
        if translated.get('merge'):
            env_criteria = tuple(translated.get(field) for field in names_envelope_criteria)
            if env_criteria in merge_yes:
                merge_yes[env_criteria][0].append(filename)
                merge_yes[env_criteria][1].append(infilename)
                merge_yes[env_criteria][2] += nrmessages
            else:
                merge_yes[env_criteria] = [[filename],[infilename],nrmessages]
        else:
            ta_info = dict((field,translated.get(field)) for field in names_envelope_criteria)
            ta_info['nrmessages'] = nrmessages
            merge_no.append((ta_info, [filename],[infilename]))
    #envelope
    for env_criteria,rest_of_info in merge_yes.iteritems():
        ta_info = dict(zip(names_envelope_criteria,env_criteria))
        ta_info['filename'] = transform.unique('bots_file_name')   #create filename for enveloped message
        ta_info['nrmessages'] = rest_of_info[2]
        ta_info['infiles'] = rest_of_info[1]      #for reference: list of infilenames
        ta_info['error'] = ''
        try:
            envelope.envelope(ta_info,rest_of_info[0])
        except:
            txt = botslib.txtexc()
            ta_info['error'] = txt.strip()
        finally:
            run.outgoing.append(ta_info)
    for ta_info,filenames,infilenames in merge_no:
        ta_info['filename'] = transform.unique('bots_file_name')   #create filename for enveloped message
        ta_info['infiles'] = infilenames      #for reference: list of infilenames
        ta_info['error'] = ''
        try:
            envelope.envelope(ta_info,filenames)
        except:
            txt = botslib.txtexc()
            ta_info['error'] = txt.strip()
        finally:
            run.outgoing.append(ta_info)

     
def write_outgoing(run):
    outputdir = botslib.join(run.outpath)
    botslib.dirshouldbethere(outputdir)
    for outgoing in run.outgoing:
        if not outgoing['error']:
            try:
                unique_filename = filename_formatter(run.outfilename,outgoing)
                tofilepath = botslib.join(outputdir,unique_filename)
                fromfilepath = botslib.abspathdata(outgoing['filename'])
                shutil.move(fromfilepath,tofilepath)
            except:
                txt = botslib.txtexc()
                outgoing.update({'error':txt})
            else:
                outgoing.update({'outfilename':tofilepath})
                
def filename_formatter(filename_mask,ta_info):
    class infilestr(str):
        ''' class for the infile-string that handles the specific format-options'''
        def __format__(self, format_spec):
            if not format_spec:
                return str(self)
            name,ext = os.path.splitext(str(self))
            if format_spec == 'ext':
                if ext.startswith('.'):
                    ext = ext[1:]
                return ext 
            if format_spec == 'name':
                return name 
            raise botslib.CommunicationOutError(_(u'Error in format of "{filename}": unknown format: "%(format)s".'),
                                                {'format':format_spec})
    unique = str(botslib.unique('bots_outgoing_file_name'))   #create unique part for filename
    tofilename = filename_mask.replace('*',unique)           #filename_mask is filename in channel where '*' is replaced by idta
    if '{' in tofilename :
        if botsglobal.ini.getboolean('acceptance','runacceptancetest',False):
            datetime_object = datetime.datetime.strptime("2013-01-23 01:23:45", "%Y-%m-%d %H:%M:%S")
        else:
            datetime_object = datetime.datetime.now()
        infilename = infilestr(os.path.basename(ta_info['infiles'][0])) #there is always an infile!
        tofilename = tofilename.format(infile=infilename,datetime=datetime_object,**ta_info)
    return tofilename


def trace(run):
    for incoming in run.incoming:
        if incoming['error']:
            run.errorinrun += 1
            continue
        #note: no search in translated: errors are in run.incoming
        #search in outgoing for envelope errors
        if run.outgoing:    #if no translation is done
            found = False
            for outgoing in run.outgoing:
                if incoming['infilename'] in outgoing['infiles']:
                    found = True
                    if outgoing['error']:
                        incoming['error'] += outgoing['error']
            if not found:   #debug sanity check
                raise Exception('incoming not in outgoing!')
    #count enveloping errors; delete these (no valid output)
    newlist = []
    for outgoing in run.outgoing:
        if outgoing['error']:
            run.errorinrun += 1
        else:
            newlist.append(outgoing)
    run.outgoing = newlist
        
def dict2xml(d):
    def makenode(tag,content):
        node = ET.Element(tag)
        if not content:
            pass    #empty element
        elif isinstance(content, basestring):
            node.text = content
        elif isinstance(content, list):
            node.tag = tag + '_list'    #change node tag
            for element in content:
                node.append(makenode(tag, element))
        elif isinstance(content, dict):
            for key,value in content.items():
                node.append(makenode(key, value))
        else: 
            node.text = repr(content)
        return node
    assert isinstance(d, dict) and len(d) == 1
    for key,value in d.items():
        node = makenode(key,value)
    botslib.indent_xml(node)
    return ET.tostring(node)

def filter(lijst,names):
    return [dict((k,v) for k,v in d.items() if k in names) for d in lijst]
    
def report(run):
    in_filter = ('infilename','error')
    out_filter = ('outfilename','editype','messagetype','frompartner','topartner','infiles','nrmessages')
    #~ print '\nFound',run.errorinrun,'errors.'
    #~ print '\nIncoming:'
    #~ for incoming in filter(run.incoming,in_filter):
        #~ for name,value in incoming.items():
            #~ print name,':',value,' ',
        #~ print
    #~ print '\nOutgoing:'
    #~ for outgoing in run.outgoing:
        #~ for name in out_filter:
            #~ print name,':',outgoing.get(name),
        #~ print
        #~ print '    from files:',outgoing.get('infiles')
    
    #~ print '\nEngine is done.\n'
    xml_string = dict2xml({'root':{'errors':run.errorinrun,'incoming':filter(run.incoming,in_filter),'outgoing':filter(run.outgoing,out_filter)}})
    print xml_string

def cleanup(run):
    shutil.rmtree(data_storage,ignore_errors=True)


if __name__ == '__main__':
    start()

'''
experiemtn with translation rule:

l = [{'alt': u'', 'fromeditype': u'edifact', 'frommessagetype': u'ORDERSD96AUNEAN008', 'frompartner': None, 'topartner': None, 'toeditype': u'xml', 'tomessagetype': u'orders', 'tscript': u'orders_edifact2xml'},
    {'alt': u'', 'fromeditype': u'edifact', 'frommessagetype': u'ORDERSD96AUNEAN008', 'frompartner': None, 'topartner': None, 'toeditype': u'xml', 'tomessagetype': u'orders', 'tscript': u'orders_edifact2xml'},
    ]

#first step: selecting for fromeditype,frommessagetype (active)
first = True
for d in l:
    if d['fromeditype'] != fromeditype or d['frommessagetype'] != frommessagetype:
        continue
    if (d['alt']!='' and d['alt']!=alt) or (d['frompartner'] is not None and d['frompartner']!=frompartner) or (d['frompartner'] is not None and d['frompartner']!=frompartner):
        continue
        
    if first:
        bestchoice = d
        continue
    #old algoritm: sort by alt, frompartner,topartner; pick first one in sort order
    #alt: either '' or value as in message
    if d['alt']
    #best choice: alt,frompartner and topartner
    #d: alt, 
    #if 

'''