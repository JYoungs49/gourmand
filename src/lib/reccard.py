#!/usr/bin/env python
import gtk.glade, gtk, gobject, os.path, time, os, sys, re, threading, gtk.gdk, Image, StringIO, pango, string
import xml.sax.saxutils
import exporters
import convert, TextBufferMarkup
from recindex import RecIndex
import prefs, WidgetSaver, timeEntry, Undo, ratingWidget
import keymanager
import dialog_extras as de
from dialog_extras import show_amount_error
import treeview_extras as te
import cb_extras as cb
import exporters.printer as printer
from gdebug import *
from gglobals import *
from nutrition.nutritionLabel import NutritionLabel
from gettext import gettext as _
from gettext import ngettext
import ImageExtras as ie
from importers.importer import parse_range
from FauxActionGroups import ActionManager
import mnemonic_manager

import LinkedTextView

class RecCard (WidgetSaver.WidgetPrefs,ActionManager):
    """Our basic recipe card."""

    HIDEABLE_WIDGETS = [
        ('handlebox','Toolbar'),
        ('imageFrame','Image'),
        ('ieHandlebox','Ingredient Editor'),
        (['servingsLabel','servingsBox','rcMultCheck'],'Servings'),
        (['cuisineLabel','cuisineBox'],'Cuisine'),
        (['categoryLabel','categoryBox'],'Category'),
        (['preptimeLabel','preptimeBox'],'Preparation Time'),
        (['cooktimeLabel','cooktimeBox'],'Cooking Time'),
        (['ratingLabel','ratingBox'],'Rating'),
        (['sourceLabel','sourceBox'],'Source'),
        #(['instrExp'],'Instructions'),
        #(['modExp'],'Modifications'),
        ]

    def __init__ (self, RecGui, recipe=None):
        debug("RecCard.__init__ (self, RecGui):",5)
        self.setup_defaults()
        t=TimeAction('RecCard.__init__ 1',0)
        self.mult=1
        self.rg = RecGui
        self.rg = RecGui
        self.prefs = self.rg.prefs
        self.rd = self.rg.rd
        self.nd = self.rg.nd
        self.makeTimeEntry = lambda *args: timeEntry.makeTimeEntry()
        self.makeStarButton = lambda *args: ratingWidget.make_star_button(self.rg.star_generator)
        self.makeStarImage = lambda *args: ratingWidget.make_star_image(self.rg.star_generator)
        self.makeLinkedTextView = lambda *args: LinkedTextView.LinkedTextView()
        self.makeNutritionLabel = lambda *args: NutritionLabel(self.prefs)
        def custom_handler (glade,func_name,
                            widg, s1,s2,i1,i2):
            f=getattr(self,func_name)
            w= f(s1,s2,i1,i2)
            return w
        gtk.glade.set_custom_handler(custom_handler)
        self.glade = gtk.glade.XML(os.path.join(gladebase,'recCard.glade'))
        self.ie = IngredientEditor(self.rg, self)        
        self.mm = mnemonic_manager.MnemonicManager()
        self.mm.add_glade(self.glade)
        nlb=self.glade.get_widget('nutritionLabel').edit_missing_button.get_child().get_child().get_children()[1]
        self.mm.add_widget_mnemonic(nlb)
        self.mm.fix_conflicts_peacefully()
        # Manually fixing this particular mnemonic for English...
        if nlb.get_text()=='Edit':
            print 'manual fixup...'
            nlb.set_markup_with_mnemonic('Ed_it')
        # Do some funky style modifications...
        display_toplevel_widget = self.glade.get_widget('displayPanes')
        new_style = display_toplevel_widget.get_style().copy()
        cmap = display_toplevel_widget.get_colormap()
        new_style.bg[gtk.STATE_NORMAL]= cmap.alloc_color('white')
        new_style.bg[gtk.STATE_INSENSITIVE] = cmap.alloc_color('white')
        new_style.fg[gtk.STATE_NORMAL]= cmap.alloc_color('black')
        new_style.fg[gtk.STATE_INSENSITIVE] = cmap.alloc_color('black')
        def set_style (widg, styl):
            if (not isinstance(widg,gtk.Button) and
                not isinstance(widg,gtk.Entry) and
                not isinstance(widg,gtk.Separator)
                ): widg.set_style(styl)
            if hasattr(widg,'get_children'):
                for c in widg.get_children(): set_style(c,styl)
        set_style(display_toplevel_widget,new_style)
        t.end()
        t=TimeAction('RecCard.__init__ 2',0)        
        self.setup_action_manager()
        self.get_widgets()
        self.register_pref_dialog()
        self.history = Undo.MultipleUndoLists(self.undo,self.redo,
                                              get_current_id=self.notebook.get_current_page
                                              )
        self.NOTEBOOK_DISPLAY_PAGE = 0
        self.NOTEBOOK_ATTR_PAGE = 1
        self.notebook_pages = {self.NOTEBOOK_DISPLAY_PAGE:'display',
                               self.NOTEBOOK_ATTR_PAGE:'attributes',
                               2:'ingredients',
                               3:'instructions',
                               4:'modifications'}
        
        def hackish_notebook_switcher_handler (*args):
            # because the switch page signal happens before switching...
            # we'll need to look for the switch with an idle call
            gobject.idle_add(self.notebookChangeCB)
        self.notebook.connect('switch-page',hackish_notebook_switcher_handler)
        #self.notebook.set_current_page(0)        
        self.page_specific_handlers = []
        self.notebookChangeCB()
        self.create_ingTree()
        self.selection=True
        self.selection_changed()
        self.initRecipeWidgets()
        self.setEdited(False)
        self.images = []
        self.new = True
        if recipe:
            self.updateRecipe(recipe)
            self.new = False
        else:
            r=self.rg.rd.new_rec()
            self.new = True
            self.updateRecipe(r)
            # and set our page to the details page
            self.notebook.set_current_page(1)
        self.setEditMode(self.new)
        t.end()
        t=TimeAction('RecCard.__init__ 4',0)
        self.pref_id = 'rc%s'%self.current_rec.id
        self.conf = []
        self.conf.append(WidgetSaver.WindowSaver(self.widget, self.prefs.get(self.pref_id,{})))        
        self.glade.signal_autoconnect({
            'rc2shop' : self.addToShopL,
            'rcDelete' : self.delete,
            'rcHide' : self.hide,
            'saveEdits': self.saveEditsCB,
            'addIng' : self.newIngCB,
            'newRec' : self.newRecipeCB,
            'rcToggleMult' : self.multTogCB,
            'toggleEdit' : self.saveEditsCB,
            'rcSave' : self.saveAs,
            'rcEdited' : self.setEdited,
            'setRecImage' : self.ImageBox.set_from_fileCB,
            'delRecImage' : self.ImageBox.removeCB,
            'instrAddImage' : self.addInstrImageCB,
            'rcRevert' : self.revertCB,
            #'ieUp' : self.ingUpCB,
            #'ieDown' : self.ingDownCB,
            #'ieNewGroup' : self.ingNewGroupCB,
            'recRef':lambda *args: RecSelector(self.rg,self),
            #'importIngs': self.importIngredientsCB,
            'unitConverter': self.rg.showConverter,
            'ingKeyEditor': self.rg.showKeyEditor,
            'print': self.print_rec,
            'email': self.email_rec,
            'preferences':self.show_pref_dialog,
            'forget_remembered_optionals':self.forget_remembered_optional_ingredients,
            'show_help': lambda *args: de.show_faq(HELP_FILE,jump_to='Entering and Editing recipes')
            })
        self.show()
        t.end()
        # hackish, but focus was acting funny        
        #self.rw['title'].grab_focus()

    def setup_defaults (self):
        self.mult = 1
        #self.serves = float(self.serveW.get_text())
        self.default_title = _("Recipe Card: ")

    def get_widgets (self):
        t=TimeAction('RecCard.get_widgets 1',0)
        self.timeB = self.glade.get_widget('preptimeBox')
        self.timeB.connect('changed',self.setEdited)
        self.nutritionLabel = self.glade.get_widget('nutritionLabel')
        self.nutritionLabel.connect('ingredients-changed',
                                    lambda *args: self.resetIngredients()
                                    )
        self.display_info = ['title','rating','preptime',
                             'servings','cooktime','source',
                             'cuisine','category','instructions',
                             'modifications','ingredients']
        for attr in self.display_info:
            setattr(self,'%sDisplay'%attr,self.glade.get_widget('%sDisplay'%attr))
            setattr(self,'%sDisplayLabel'%attr,self.glade.get_widget('%sDisplayLabel'%attr))
        self.servingsDisplaySpin = self.glade.get_widget('servingsDisplaySpin')
        self.servingsDisplaySpin.connect('changed',self.servingsChangeCB)
        self.servingsMultiplyByLabel = self.glade.get_widget('multiplyByLabel')
        self.multiplyDisplaySpin = self.glade.get_widget('multiplyByDisplaySpin')
        self.multiplyDisplaySpin.connect('changed',self.multChangeCB)
        self.multiplyDisplayLabel = self.glade.get_widget('multiplyByDisplayLabel')
        self.ingredientsDisplay.connect('link-activated',
                                        self.show_recipe_link_cb)
        self.special_display_functions = {
            'servings':self.updateServingsDisplay,
            'ingredients':self.updateIngredientsDisplay,
            'title':self.updateTitleDisplay,
            }
        t.end()
        t=TimeAction('RecCard.get_widgets 2',0)
        WidgetSaver.WidgetPrefs.__init__(
            self,
            self.prefs,
            glade=self.glade,
            hideable_widgets=self.HIDEABLE_WIDGETS,
            basename='rc_hide_')
        t.end()
        t=TimeAction('RecCard.get_widgets 3',0)
        self.ImageBox = ImageBox(self)
        self.rg.sl.sh.init_orgdic()
        self.selected=True
        #self.serveW = self.glade.get_widget('servingsBox')
        #self.multCheckB = self.glade.get_widget('rcMultCheck')
        self.multLabel = self.glade.get_widget('multLabel')
        self.applyB = self.glade.get_widget('saveButton')
        self.revertB = self.glade.get_widget('revertButton')
        self.widget = self.glade.get_widget('recCard')
        self.stat = self.glade.get_widget('statusbar1')
        self.contid = self.stat.get_context_id('main')
        self.toggleReadableMenu = self.glade.get_widget('toggle_readable_units_menuitem')
        self.toggleReadableMenu.set_active(self.prefs.get('readableUnits',True))
        self.toggleReadableMenu.connect('toggled',self.readableUnitsCB)
        # this hook won't spark an infinite loop since the 'toggled' signal is only emitted
        # for a *change*
        def toggle_readable_hook (p,v):
            if p=='readableUnits': self.toggleReadableMenu.set_active(v)
        self.rg.prefs.set_hooks.append(toggle_readable_hook)
        self.notebook=self.glade.get_widget('notebook1')        
        t.end()
        
    def setup_action_manager(self):
        ActionManager.__init__(
            self,self.glade,
            # action groups
            {'ingredientGroup':[{'ingAdd':[{'tooltip':_('Add new ingredient to the list.'),
                                            'separators':'ingSeparator'},
                                           ['addIngButton','ingAddMenu']]},
                                {'ingGroup':[{'tooltip':_('Create new subgroup of ingredients.'),},
                                             ['ingNewGroupButton','ingNewGroupMenu']]},
                                {'ingImport':[{'tooltip':_('Import list of ingredients from text file.'),
                                               'separators':'ingSeparator3'
                                               },
                                              ['ingImportListButton','ingImportListMenu'],
                                              ]
                                 },
                                {'ingPaste':[{'tooltip':_('Paste list of ingredients from clipboard.')},
                                             ['pasteIngredientButton','pasteIngredientMenu']]
                                 },
                                {'ingRecRef':[{'tooltip':_('Add another recipe as an "ingredient" in the current recipe.'),
                                               'separators':'ingSeparator3'
                                               },
                                              ['ingRecRefButton','ingRecRefMenu']]},
                                #{'ingSeparators':[{'label':None,'stock-id':None,'tooltip':None},['ingSeparator','ingSeparator2']]}
                                ],
             'selectedIngredientGroup':[{'ingDel':[{'tooltip':_('Delete selected ingredient')},
                                                   ['ingDelButton','ingDelMenu']]},
                                        {'ingUp':[{'tooltip':_('Move selected ingredient up.'),
                                                   'separators':'ingSeparator2'},
                                                  ['ingUpButton','ingUpMenu']]},
                                        {'ingDown':[{'tooltip':_('Move selected ingredient down.')},
                                                    ['ingDownButton','ingDownMenu']]},
                                        ],
             'editTextItems':[{p: [{'separators':'formatSeparator'},
                                   ['%sButton'%p,'%sButton2'%p,'%sMenu'%p]]} for p in 'bold','italic','underline'],
             'genericEdit':[{'copy':[{},['copyButton','copyButton2','copyMenu']]},
                            {'paste':[{'separators':'copySeparator'},['pasteButton','pasteButton2','pasteMenu',]]},
                            ],
             'undoButtons':[{'undo':[{},['undoButton','undoMenu']]},
                            {'redo':[{},['redoButton','redoMenu']]},
                            ],
             'editButtons':[{'edit':[{'tooltip':_("Toggle whether we're editing the recipe card")},
                                     ['editButton','editMenu']]},
                            ],
             'saveButtons':[{'save':[{},['saveButton','saveMenu']]},
                            {'revert':[{},['revertButton','revertMenu'],]},]
             },
            # callbacks
            [('ingUp',self.ingUpCB),
             ('ingDown',self.ingDownCB),
             ('ingAdd',self.ie.new),
             ('ingDel',self.ie.delete_cb),
             ('ingGroup',self.ingNewGroupCB),
             ('ingImport',self.importIngredientsCB),
             ('ingPaste',self.pasteIngsCB),
             ('edit',self.editCB),
             ]
            )
        self.notebook_page_actions = {'ingredients':['ingredientGroup','selectedIngredientGroup'],
                                      'instructions':['editTextItems'],
                                      'modifications':['editTextItems'],
                                      }
        # for editText stuff is not yet implemented!
        # it appears it will be quite a pain to implement as well, alas!
        # see bug 59390: http://bugzilla.gnome.org/show_bug.cgi?id=59390
        #self.editTextItems.set_visible(False)
        self.genericEdit.set_visible(False)
        import sets
        self.notebook_changeable_actions = sets.Set()
        for aa in self.notebook_page_actions.values():
            for a in aa:
                self.notebook_changeable_actions.add(a)

    def register_pref_dialog (self, *args):
        """Add our GUI prefs to the preference dialog."""
        options = self.make_option_list()
        if hasattr(self.rg,'rec_apply_list'):
            self.rg.rec_apply_list.append(self.apply_option)
        else:
            # make a list of open reccard's "apply" functions
            self.rg.rec_apply_list = [self.apply_option]
            # make a function to call these apply functions for each open item
            self.rg.apply_rec_options = lambda *args: [cb(*args) for cb in self.rg.rec_apply_list]
            self.rg.prefsGui.add_pref_table(options,
                                            'cardViewVBox',
                                            self.rg.apply_rec_options
                                            )
        
    def show_pref_dialog (self, *args):
        """Show our preference dialog for the recipe card."""
        self.rg.prefsGui.show_dialog(page=self.rg.prefsGui.CARD_PAGE)

    def notebookChangeCB (self, *args):
        page=self.notebook.get_current_page()
        self.history.switch_context(page)
        while self.page_specific_handlers:
            w,s = self.page_specific_handlers.pop()
            if w.handler_is_connected(s):
                w.disconnect(s)
        debug('notebook changed to page: %s'%page,3)
        if self.notebook_pages.has_key(page):
            page=self.notebook_pages[page]
        else:
            debug('WTF, %s not in %s'%(page,self.notebook_pages),1)
        debug('notebook on page: %s'%page,3)
        for actionGroup in self.notebook_changeable_actions:
            if self.notebook_page_actions.has_key(page):
                getattr(self,actionGroup).set_visible(actionGroup in self.notebook_page_actions[page])
                if not actionGroup in self.notebook_page_actions[page]: debug('hiding actionGroup %s'%actionGroup,3)
                if actionGroup in self.notebook_page_actions[page]: debug('showing actionGroup %s'%actionGroup,3)
            else:
                getattr(self,actionGroup).set_visible(False)
        if 'instructions'==page:
            buf = self.rw['instructions'].get_buffer()
            c1=buf.setup_widget_from_pango(self.bold, '<b>bold</b>')
            c2=buf.setup_widget_from_pango(self.italic, '<i>ital</i>')
            c3=buf.setup_widget_from_pango(self.underline, '<u>underline</u>')
            self.page_specific_handlers = [(buf,c1),(buf,c2),(buf,c3)]
        if 'modifications'==page:
            buf = self.rw['modifications'].get_buffer()
            c1=buf.setup_widget_from_pango(self.bold, '<b>bold</b>')
            c2=buf.setup_widget_from_pango(self.italic, '<i>ital</i>')
            c3=buf.setup_widget_from_pango(self.underline, '<u>underline</u>')
            self.page_specific_handlers = [(buf,c1),(buf,c2),(buf,c3)]

    def multTogCB (self, w, *args):
        debug("multTogCB (self, w, *args):",5)
        return
        if not self.multCheckB.get_active():
            old_mult = self.mult
            self.mult = 1
            self.multLabel.set_text("")
            if old_mult != self.mult:
                self.imodel = self.create_imodel(self.current_rec,mult=self.mult)
                self.ingTree.set_model(self.imodel)
                self.selection_changed()
                self.ingTree.expand_all()
                self.serveW.set_value(float(self.serves_orig))
        
    def modTogCB (self, w, *args):
        debug("modTogCB (self, w, *args):",5)
        if w.get_active():
            self.rw['modifications'].show()
        else:
            self.rw['modifications'].hide()

    def show_recipe_link_cb (self, widg, link):
        rid,rname = link.split(':')
        rec = self.rg.rd.get_rec(int(rid))
        if not rec:
            rec = self.rg.rd.fetch_one(
                self.rg.rd.rview,
                title=rname
                )
        if rec:
            self.rg.openRecCard(rec)
        else:
            de.show_message(parent=self.widget,
                            label=_('Unable to find recipe %s in database.')%rname
                            )
            
    def instrTogCB (self, w, *args):
        debug("instrTogCB (self, w, *args):",5)
        if w.get_active():
            self.rw['instructions'].show()
        else:
            self.rw['instructions'].hide()

    def readableUnitsCB (self, widget):
        if widget.get_active():
            self.prefs['readableUnits']=True
            self.resetIngList()
        else:
            self.prefs['readableUnits']=False
            self.resetIngList()

    def addInstrImage (self, file):
        debug("addInstrImage (self, file):",5)
        w = self.rw['instructions']
        i = gtk.Image()
        i.set_from_file(file)
        pb=i.get_pixbuf()
        i=None
        b=w.get_buffer()
        iter=b.get_iter_at_offset(0)
        anchor = b.create_child_anchor(iter)
        self.images.append((anchor,pb))
        b.insert_pixbuf(iter,pb)

    def addInstrImageCB (self, *args):
        debug("addInstrImageCB (self, *args):",5)
        f = de.select_file(_("Choose an image to insert in instructions... "),action=gtk.FILE_CHOOSER_ACTION_OPEN)
        self.addInstrImage(f)

    def saveEditsCB (self, click=None, click2=None, click3=None):
        debug("saveEditsCB (self, click=None, click2=None, click3=None):",5)
        self.rg.message("Committing edits!")
        self.setEdited(False)
        self.new = False
        newdict = {'id': self.current_rec.id}
        for c in self.reccom:
            newdict[c]=self.rw[c].entry.get_text()
        for e in self.recent:
            if e in INT_REC_ATTRS: newdict[e]=self.rw[e].get_value()
            else: newdict[e]=self.rw[e].get_text()
        for t in self.rectexts:
            buf = self.rw[t].get_buffer()
            newdict[t]=buf.get_text(buf.get_start_iter(),buf.get_end_iter())
        if self.ImageBox.edited:
            self.ImageBox.commit()
            self.ImageBox.edited=False
            newdict['thumb']=self.current_rec.thumb
            newdict['image']=self.current_rec.image
        debug("modify_rec, newdict=%s"%newdict,1)
        self.current_rec = self.rg.rd.modify_rec(self.current_rec,newdict)
        # save DB for metakit
        self.rg.rd.save()
        #print 'saved','\nupdating...'
        ## if our title has changed, we need to update menus
        self.updateRecDisplay()
        self.rg.rmodel.update_recipe(self.current_rec)
        #print 'udpated'
        if newdict.has_key('title'):
            self.widget.set_title("%s %s"%(self.default_title,self.current_rec.title))
            self.rg.updateViewMenu()
        
    def delete (self, *args):
        debug("delete (self, *args):",2)
        self.rg.recTreeDeleteRecs([self.current_rec])
        debug("delete finished",2)
    
    def addToShopL (self, *args):
        debug("addToShopL (self, *args):",5)
        import shopgui
        d = shopgui.getOptionalIngDic(self.rg.rd.get_ings(self.current_rec),
                                      self.mult,
                                      self.prefs,
                                      self.rg)
        self.rg.sl.addRec(self.current_rec,self.mult,d)
        self.rg.sl.show()

    def servingsChangeCB (self, widg):
        val=widg.get_value()
        self.updateServingMultiplierLabel(val)
        self.updateIngredientsDisplay()

    def multChangeCB (self, widg):
        self.mult=widg.get_value()
        self.updateIngredientsDisplay()
        
    def initRecipeWidgets (self):
        debug("initRecipeWidgets (self):",5)
        self.rw = {}
        self.recent = []
        self.reccom = []        
        for a,l,w in REC_ATTRS:
            if w=='Entry': self.recent.append(a)
            elif w=='Combo': self.reccom.append(a)
            else: raise "REC_ATTRS widget type %s not recognized"%w
        self.rectexts = ['instructions', 'modifications']
        for a in self.reccom:
            self.rw[a]=self.glade.get_widget("%sBox"%a)
            self.rw[a].get_children()[0].connect('changed',self.changedCB)
        for a in self.recent:
            self.rw[a]=self.glade.get_widget("%sBox"%a)
            self.rw[a].connect('changed',self.changedCB)
        for t in self.rectexts:
            self.rw[t]=self.glade.get_widget("%sText"%t)
            buf = TextBufferMarkup.InteractivePangoBuffer()
            self.rw[t].set_buffer(buf)
            buf.connect('changed',self.changedCB)        

    def newRecipeCB (self, *args):
        debug("newRecipeCB (self, *args):",5)
        self.rg.newRecCard()

    def getSelectedIters (self):
        if len(self.imodel)==0:
            return None
        ts,paths = self.ingTree.get_selection().get_selected_rows()
        return [ts.get_iter(p) for p in paths]

    def getSelectedIter (self):
        debug("getSelectedIter",4)
        if len(self.imodel)==0:
            return None
        try:
            ts,paths=self.ingTree.get_selection().get_selected_rows()
            lpath=paths[-1]
            group=ts.get_iter(lpath)
        except:
            debug("getSelectedIter: there was an exception",0)            
            group=None
        return group

    def newIngCB (self, *args):
        d={'id':self.current_rec.id}
        ing=self.rg.rd.add_ing(d)
        group=self.getSelectedIter()
        debug("group=%s"%group,5)
        iter=self.add_ingredient(self.imodel,ing,self.mult,group) #we return iter
        path=self.imodel.get_path(iter)
        # open up (in case we're in a group)
        self.ingTree.expand_to_path(path)
        self.ingTree.set_cursor(path,self.ingColsByName[_('Amt')])
        #self.ingTree.get_selection().select_iter(iter)
        self.ingTree.grab_focus()
        self.updateIngredientsDisplay()
        self.message(_('Changes to ingredients saved automatically.'))

    def ingUpCB (self, *args):
        ts,paths = self.ingTree.get_selection().get_selected_rows()
        iters = [ts.get_iter(p) for p in paths]
        u=Undo.UndoableObject(lambda *args: self.ingUpMover(ts,paths),
                              lambda *args: self.ingDownMover(ts,[ts.get_path(i) for i in iters]),
                              self.history)
        u.perform()

    def ingUpMover (self, ts, paths):
        def moveup (ts, path, itera):
            if itera:
                prev=self.path_next(path,-1)
                prev_iter=ts.get_iter(prev)
                te.move_iter(ts,itera,sibling=prev_iter,direction="before")
                self.ingTree.get_selection().unselect_path(path)
                self.ingTree.get_selection().select_path(prev)
        self.pre_modify_tree()
        paths.reverse()
        for p in paths:
            itera = ts.get_iter(p)
            moveup(ts,p,itera)
        self.commit_positions()
        self.post_modify_tree()
        
    def ingDownCB (self, *args):
        ts,paths = self.ingTree.get_selection().get_selected_rows()
        iters = [ts.get_iter(p) for p in paths]
        u=Undo.UndoableObject(lambda *args: self.ingDownMover(ts,paths),
                              lambda *args: self.ingUpMover(ts,[ts.get_path(i) for i in iters]),
                              self.history)
        u.perform()
        
    def ingDownMover (self, ts, paths):
        #ts, itera = self.ingTree.get_selection().get_selected()
        def movedown (ts, path, itera):
            if itera:
                next = ts.iter_next(itera)
                te.move_iter(ts,itera,sibling=next,direction="after")
                if next:
                    next_path=ts.get_path(next)
                else:
                    next_path=path
                self.ingTree.get_selection().unselect_path(path)
                self.ingTree.get_selection().select_path(self.path_next(next_path,1))
        self.pre_modify_tree()
        paths.reverse()
        for p in paths:
            itera = ts.get_iter(p)
            movedown(ts,p,itera)
            #selected_foreach(movedown)
        self.commit_positions()
        self.post_modify_tree()
        
    def path_next (self, path, inc=1):
        """Return the path NEXT rows after PATH. Next can be negative, in
        which case we get previous paths."""
        next=list(path[0:-1])
        last=path[-1]
        last += inc
        if last < 0:
            last=0
        next.append(last)
        next=tuple(next)
        return next

    def ingNewGroupCB (self, *args):
        self.add_group(de.getEntry(label=_('Adding Ingredient Group'),
                                   sublabel=_('Enter a name for new subgroup of ingredients'),
                                   entryLabel=_('Name of group: '),
                                   ),
                       self.imodel,
                       prev_iter=self.getSelectedIter(),
                       children_iters=self.getSelectedIters())
        self.commit_positions()

    def resetIngList (self):
        debug("resetIngList (self, rec=None):",0)
        self.ing_alist = None
        self.imodel = self.create_imodel(self.current_rec,mult=self.mult)
        self.ingTree.set_model(self.imodel)        
        self.selection_changed()
        self.ingTree.expand_all()
        self.updateIngredientsDisplay()

    def updateAttribute (self, attr, value):
        """Update our recipe card to reflect attribute:value.

        We assume the attribute has already been set for the recipe.
        This function is meant to make us properly reflect external
        changes."""
        if self.rw.has_key(attr):
            if attr in self.reccom: self.rw[attr].entry.set_text(value)
            elif attr in INT_REC_ATTRS: self.rw[attr].entry.set_value(value)
            elif attr in self.recent: self.rw[attr].set_text(value)
            elif attr in self.rectexts: self.rw[attr].get_buffer().set_text(value)
            # update title if necessary
            if attr=='title': self.widget.set_title(value)
        self.updateRecDisplay()
            
    def updateRecipe (self, rec, show=True):
        debug("updateRecipe (self, rec):",0)
        if type(rec) == int:
            rec=self.rg.rd.fetch_one(self.rg.rd.rview,id=rec)
        if not self.edited or de.getBoolean(parent=self.widget,
                                            label=_("Abandon your edits to %s?")%self.current_rec.title):
            self.updateRec(rec)
            if show:
                self.show()

    def revertCB (self, *args):
        if de.getBoolean(parent=self.widget,
                         label=_("Are you sure you want to abandon your changes?"),
                         cancel=False):
            self.updateRec(self.current_rec)

    def updateRec (self, rec):
        debug("updateRec (self, rec):",5)
        """If handed an ID, we'll grab the rec"""
        if type(rec) == type(""):
            rec=self.rg.rd.get_rec(rec)
        self.current_rec = rec
        try:
            self.serves_orig = float(self.current_rec.servings)
        except:
            self.serves_orig = None
            if hasattr(self.current_rec,'servings'):
                debug(_("Couldn't make sense of %s as number of servings")%self.current_rec.servings,0)        
        self.serves = self.serves_orig
        #self.servingsChange()
        self.resetIngList()
        self.updateRecDisplay()
        for c in self.reccom:
            debug("Widget for %s"%c,5)
            if c=='category':
                slist = self.rg.rd.get_unique_values(c,self.rg.rd.catview)
            else:
                slist = self.rg.rd.get_unique_values(c,deleted=False)
            if not slist:
                self.rg.rd.get_default_values(c)
            cb.set_model_from_list(self.rw[c],slist)
            cb.setup_completion(self.rw[c])
            if c=='category':
                val = ', '.join(self.rg.rd.get_cats(rec))
            else:
                val = getattr(rec,c)
            self.rw[c].entry.set_text(val or "")
            if isinstance(self.rw[c],gtk.ComboBoxEntry):
                Undo.UndoableEntry(self.rw[c].get_child(),self.history)
                cb.FocusFixer(self.rw[c])
            else:
                # we still have to implement undo for regular old comboBoxen!
                1
        for e in self.recent:
            if isinstance(self.rw[e],gtk.SpinButton):
                try:
                    self.rw[e].set_value(float(getattr(rec,e)))
                except:
                    debug('%s Value %s is not floatable!'%(e,getattr(rec,e)))
                    self.rw[e].set_text("")
                Undo.UndoableGenericWidget(self.rw[e],self.history)
            elif e in INT_REC_ATTRS:
                self.rw[e].set_value(int(getattr(rec,e) or 0))
                Undo.UndoableGenericWidget(self.rw[e],
                                           self.history)
            else:
                self.rw[e].set_text(getattr(rec,e) or "")
                Undo.UndoableEntry(self.rw[e],self.history)    
        for t in self.rectexts:
            w=self.rw[t]
            b=w.get_buffer()
            try:
                #txt=unicode(getattr(rec,t))
                txt = getattr(rec,t)
                if txt:
                    txt = txt.encode('utf8','ignore')
                else:
                    txt = "".encode('utf8')
                #txt = getattr(rec,t).decode()
            except UnicodeDecodeError:
                txt = getattr(rec,t)
                debug('UnicodeDecodeError... trying to force our way foreward',0)
                debug('We may fail to display this: %s'%txt,0)
                debug('Type = %s'%type(txt),0)
                raise
            b.set_text(txt)
            Undo.UndoableTextView(w,self.history)
        #self.servingsChange()
        self.ImageBox.get_image()
        self.ImageBox.edited=False
        
        self.setEdited(False)
                
    def undoableWidget (self, widget, signal='changed',
                        get_text_cb='get_text',set_text_cb='set_text'):
        if type(get_text_cb)==str: get_text_cb=getattr(widget,get_text_cb)
        if type(set_text_cb)==str: set_text_cb=getattr(widget,set_text_cb)
        txt=get_text_cb()
        utc = Undo.UndoableTextChange(set_text_cb,
                                      self.history,
                                      initial_text=txt,
                                      text=txt)
        def change_cb (*args):
            newtxt=get_text_cb()
            utc.add_text(newtxt)
        widget.connect(signal,change_cb)

    def updateRecDisplay (self):
        """Update the 'display' portion of the recipe card."""
        self.update_nutrition_info()
        for attr in self.display_info:
            if  self.special_display_functions.has_key(attr):
                debug('calling special_display_function for %s'%attr,0)
                self.special_display_functions[attr]()
            else:
                widg=getattr(self,'%sDisplay'%attr)
                widgLab=getattr(self,'%sDisplayLabel'%attr)
                if not widg or not widgLab:
                    raise 'There is no widget or label for  %s=%s, %s=%s'%(attr,widg,'label',widgLab)
                if attr=='category':
                    attval = ', '.join(self.rg.rd.get_cats(self.current_rec))
                else:
                    attval = getattr(self.current_rec,attr)
                if attval:
                    debug('showing attribute %s = %s'%(attr,attval),0)
                    if attr in INT_REC_ATTRS:
                        if attr=='rating': widg.set_value(attval)
                        elif attr in ['preptime','cooktime']:
                            widg.set_text(convert.seconds_to_timestring(attval))
                    else:
                        widg.set_text(attval)
                        if attr in ['modifications','instructions']:
                            widg.set_use_markup(True)
                    widg.show()
                    widgLab.show()
                else:
                    debug('hiding attribute %s'%attr,0)
                    widg.hide()
                    widgLab.hide()

    def list_all_ings (self, rec):
        """Return a list of ingredients suitable for nutritional
        lookup, including all optional items and ingredients contained
        in recipe-as-ingredient items.
        """
        ings = self.rd.get_ings(rec)
        ret = []
        for i in ings:
            if hasattr(i,'refid') and i.refid:
                subrec = self.rd.get_referenced_rec(i)
                if not subrec:
                    raise "WTF! Can't find ",i.refid
                ret.extend(self.list_all_ings(subrec))
                continue
            else:
                ret.append(i)
        return ret

    def update_nutrition_info (self):
        """Update nutritional information for ingredient list."""
        if self.current_rec.servings:
            self.nutritionLabel.set_servings(
                convert.frac_to_float(self.current_rec.servings)
                )
        ings = self.list_all_ings(self.current_rec)
        self.nutinfo = self.rg.nd.get_nutinfo_for_inglist(ings)
        self.nutritionLabel.set_nutinfo(self.nutinfo)

    def updateTitleDisplay (self):
        titl = self.current_rec.title
        if not titl: titl="<b>Unitled</b>"
        titl = "<b>" + xml.sax.saxutils.escape(titl) + "</b>"
        self.titleDisplay.set_text(titl)
        self.titleDisplay.set_use_markup(True)

    def updateServingsDisplay (self, serves=None):
        self.serves_orig=self.current_rec.servings
        try:
            self.serves_orig = float(self.serves_orig)
        except:
            self.serves_orig = None
        if self.serves_orig:
            # in this case, display servings spinbutton and update multiplier label as necessary
            self.servingsDisplay.show()
            self.servingsDisplayLabel.show()
            self.multiplyDisplaySpin.hide()
            self.multiplyDisplayLabel.hide()
            if serves:
                self.mult = float(serves)/float(self.serves_orig)
            else:
                self.mult = 1
                serves=float(self.serves_orig)
            self.servingsDisplaySpin.set_value(serves)
        else:
            #otherwise, display multiplier label and checkbutton
            self.servingsDisplay.hide()
            self.servingsDisplayLabel.hide()
            self.multiplyDisplayLabel.show()
            self.multiplyDisplaySpin.show()

    def updateServingMultiplierLabel (self,*args):
        serves = self.servingsDisplaySpin.get_value()
        if float(serves) != self.serves_orig:
            self.mult = float(serves)/self.serves_orig
        else:
            self.mult = 1
        if self.mult != 1:
            self.servingsMultiplyByLabel.set_text("x %s"%convert.float_to_frac(self.mult))
        else:
            self.servingsMultiplyByLabel.set_label("")

    def create_ing_alist (self):
        """Create alist ing_alist based on ingredients in DB for current_rec"""
        ings=self.rg.rd.get_ings(self.current_rec)
        self.ing_alist = self.rg.rd.order_ings( ings )        
        debug('self.ing_alist updated: %s'%self.ing_alist,1)

    def forget_remembered_optional_ingredients (self, *args):
        if de.getBoolean(parent=self.widget,
                         label=_('Forget which optional ingredients to shop for?'),
                         sublabel=_('Forget previously saved choices for which optional ingredients to shop for. This action is not reversable.'),
                         custom_yes=gtk.STOCK_OK,
                         custom_no=gtk.STOCK_CANCEL,
                         cancel=False):
            debug('Clearing remembered optional ingredients.',0)
            self.rg.rd.clear_remembered_optional_ings(self.current_rec)

    def resetIngredients (self):
        """Reset our display of ingredients based on what's in our database at present."""
        self.create_ing_alist()
        self.updateIngredientsDisplay()
        self.resetIngList()
        self.update_nutrition_info()

    def updateIngredientsDisplay (self):
        """Update our display of ingredients, only reloading from DB if this is our first time."""
        if not self.ing_alist:
            self.create_ing_alist()
        label = ""
        for g,ings in self.ing_alist:
            if g: label += "\n<u>%s</u>\n"%xml.sax.saxutils.escape(g)
            def ing_string (i):
                ing_strs = []
                amt,unit = self.make_readable_amt_unit(i)
                if amt: ing_strs.append(amt)
                if unit: ing_strs.append(unit)
                if i.item: ing_strs.append(i.item)
                if (type(i.optional)!=str and i.optional) or i.optional=='yes': 
                    ing_strs.append(_('(Optional)'))
                istr = xml.sax.saxutils.escape(' '.join(ing_strs))
                if i.refid:
                    return '<a href="%s:%s">'%(i.refid,
                                               xml.sax.saxutils.escape(i.item)
                                               )\
                           +istr+'</a>'
                else:
                    return xml.sax.saxutils.escape(istr)
            label+='\n'.join([ing_string(i) for i in ings])
            if g: label += "\n"
        if label:
            self.ingredientsDisplay.set_text(label)
            self.ingredientsDisplay.set_editable(False)
            self.ingredientsDisplay.show()
            self.ingredientsDisplayLabel.show()
        else:
            self.ingredientsDisplay.hide()
            self.ingredientsDisplayLabel.hide()
        
    def create_ingTree (self, rec=None, mult=1):
        debug("create_ingTree (self, rec=None, mult=1):        ",5)
        self.ingTree = self.glade.get_widget('ingTree')
        self.ingTree.get_selection().set_mode(gtk.SELECTION_MULTIPLE)
        self.ingTree.expand_all()
        self.head_to_att = {_('Amt'):'amount',
                            _('Unit'):'unit',
                            _('Item'):'item',
                            _('Key'):'ingkey',
                            _('Optional'):'optional',}
        self.ingColsByName = {}
        self.ingColsByAttr = {}
        self.shopmodel = gtk.ListStore(str)
        for c in self.ie.shopcats:
            self.shopmodel.append([c])
        self.ing_rows={}
        for n,head,tog,model,style in [[1,_('Amt'),False,None,None],
                                 [2,_('Unit'),False,self.rg.umodel,None],
                                 [3,_('Item'),False,None,None],
                                 [4,_('Optional'),True,None,None],
                                 [5,_('Key'),False,self.rg.inginfo.key_model,pango.STYLE_ITALIC],
                                 [6,_('Shopping Category'),False,self.shopmodel,pango.STYLE_ITALIC],
                                 ]:        
            if tog:
                renderer = gtk.CellRendererToggle()
                renderer.set_property('activatable',True)
                renderer.connect('toggled',self.ingtree_toggled_cb,4,'Optional')
                col=gtk.TreeViewColumn(head, renderer, active=n)
            else:
                if CRC_AVAILABLE and model:
                    debug('Using CellRendererCombo, n=%s'%n,0)
                    renderer = gtk.CellRendererCombo()
                    renderer.set_property('model',model)
                    renderer.set_property('text-column',0)
                else:
                    debug('Using CellRendererText, n=%s'%n,0)
                    renderer = gtk.CellRendererText()
                renderer.set_property('editable',True)
                renderer.connect('edited',self.ingtree_edited_cb,n,head)
                if head==_('Key'):
                    try:
                        renderer.connect('editing-started',
                                         self.ingtree_start_keyedit_cb)
                    except:
                        debug('Editing-started connect failed. Upgrade GTK for this functionality.',0)
                if style:
                    renderer.set_property('style',style)
                col=gtk.TreeViewColumn(head, renderer, text=n)
            self.ingColsByName[head]=col
            if self.head_to_att.has_key(head):
                self.ingColsByAttr[self.head_to_att[head]]=n
            col.set_reorderable(True)
            col.set_resizable(True)
            self.ingTree.append_column(col)
        self.setupShopPopupMenu()
        self.ingTree.connect("row-activated",self.ingTreeClickCB)
        self.ingTree.connect("button-press-event",self.ingtree_click_cb)
        self.ingTree.get_selection().connect("changed",self.selection_changedCB)
        self.ingTree.show()
        ## add drag and drop support
        #self.ingTree.drag_dest_set(gtk.DEST_DEFAULT_ALL,
        #                           [("text/plain",0,0)],
        #                           gtk.gdk.ACTION_COPY)
        targets=[('GOURMET_INTERNAL', gtk.TARGET_SAME_WIDGET, 0),
                 ('text/plain',0,1),
                 ('STRING',0,2),
                 ('STRING',0,3),
                 ('COMPOUND_TEXT',0,4),
                 ('text/unicode',0,5),]
        self.ingTree.enable_model_drag_source(gtk.gdk.BUTTON1_MASK,
                                              targets,
                                              gtk.gdk.ACTION_DEFAULT |
                                              gtk.gdk.ACTION_COPY |
                                              gtk.gdk.ACTION_MOVE)
        self.ingTree.enable_model_drag_dest(targets,
                                            gtk.gdk.ACTION_DEFAULT | gtk.gdk.ACTION_COPY | gtk.gdk.ACTION_MOVE)
        self.ingTree.connect("drag_data_received",self.dragIngsRecCB)
        self.ingTree.connect("drag_data_get",self.dragIngsGetCB)
        if self.rg.rd.fetch_len(self.rg.rd.rview) > 1:
            if not rec:
                rec = self.rg.rd.rview[1]
            self.imodel = self.create_imodel(rec, mult=1)
            self.ingTree.set_model(self.imodel)
            self.selection_changed()
            self.ingTree.expand_all()
            #self.ingTree.set_search_column(self.ingTreeSearchColumn)
            self.ingTree.set_search_equal_func(self.my_isearch)

    def my_isearch (self, mod, col, key, iter, data=None):
        # we ignore column info and search by item
        val = mod.get_value(iter,3)
        # and by key
        if val:
            val += mod.get_value(iter,5)
            if val.lower().find(key.lower()) != -1:
                return False
            else:
                return True
        else:
            val = mod.get_value(iter,1)
            if val and val.lower().find(key.lower())!=-1:
                return False
            else:
                return True
        
    def ingtree_click_cb (self, tv, event):
        debug("ingtree_click_cb",5)
        if CRC_AVAILABLE: return False # in this case, popups are handled already!
        x = int(event.x)
        y = int(event.y)
        time = event.time
        try:
            path, col, cellx, celly = tv.get_path_at_pos(x,y)
        except: return
        debug("ingtree_click_cb: path=%s, col=%s, cellx=%s, celly=%s"%(path,
                                                     col,
                                                     cellx,
                                                     celly),
              5)
        if col.get_title()==_('Shopping Category'):
            tv.grab_focus()
            tv.set_cursor(path,col,0)
            self.shoppop_iter=tv.get_model().get_iter(path)
            self.shoppop.popup(None,None,None,0,0)
            return True

    def setupShopPopupMenu (self):
        if CRC_AVAILABLE: return #if we have the new cellrenderercombo, we don't need this
        self.shoppop = gtk.Menu()
        new = gtk.MenuItem(_('New Category'))
        self.shoppop.append(new)
        new.connect('activate',self.shop_popup_callback,False)
        new.show()
        sep = gtk.MenuItem()
        self.shoppop.append(sep)
        sep.show()
        for i in self.rg.sl.sh.get_orgcats():
            itm = gtk.MenuItem(i)
            self.shoppop.append(itm)
            itm.connect('activate',self.shop_popup_callback,i)
            itm.show()

    def shop_popup_callback (self, menuitem, i):
        """i is our new category. If i==False, we prompt for
        a category."""
        regenerate_menu=False
        #colnum for key=5
        mod=self.ingTree.get_model()
        key=mod.get_value(self.shoppop_iter,5)
        debug('shop_pop_callback with key %s'%key,5)
        if not i:
            i=de.getEntry(label=_("Category to add %s to")%key,
                       parent=self.widget)
            if not i:
                return
            regenerate_menu=True
        self.rg.sl.orgdic[key]=i
        mod.set_value(self.shoppop_iter,6,i)
        if regenerate_menu:
            self.setupShopPopupMenu()

    def selection_changedCB (self, *args):
        v=self.ingTree.get_selection().get_selected_rows()[1]
        if v: selected=True
        else: selected=False
        self.selection_changed(v)
        return True
    
    def selection_changed (self, selected=False):
        if selected != self.selected:
            if selected: self.selected=True
            else: self.selected=False
            self.selectedIngredientGroup.set_sensitive(self.selected)

    def ingtree_toggled_cb (self, cellrenderer, path, colnum, head):
        debug("ingtree_toggled_cb (self, cellrenderer, path, colnum, head):",5)
        store=self.ingTree.get_model()
        iter=store.get_iter(path)
        val = store.get_value(iter,colnum)
        newval = not val
        store.set_value(iter,colnum,newval)
        ing=store.get_value(iter,0)
        if head==_('Optional'):
            if newval: newval=True
            else: newval=False
            self.rg.rd.undoable_modify_ing(
                ing,
                {'optional':newval},self.history,
                make_visible= lambda ing,dic: self.showIngredientChange(iter,dic))
        
    def ingtree_start_keyedit_cb (self, renderer, cbe, path_string):
        debug('ingtree_start',0)
        indices = path_string.split(':')
        path = tuple( map(int, indices))
        store = self.ingTree.get_model()
        iter = store.get_iter(path)
        itm=store.get_value(iter,self.ingColsByAttr['item'])
        mod = renderer.get_property('model')
        myfilter=mod.filter_new()
        cbe.set_model(myfilter)
        myKeys = self.rg.rd.key_search(itm)
        vis = lambda m, iter: m.get_value(iter,0) and (m.get_value(iter,0) in myKeys or m.get_value(iter,0).find(itm) > -1)
        myfilter.set_visible_func(vis)
        myfilter.refilter()
        
    def ingtree_edited_cb (self, renderer, path_string, text, colnum, head):
        debug("ingtree_edited_cb (self, renderer, path_string, text, colnum, head):",5)
        indices = path_string.split(':')
        path = tuple( map(int, indices))
        store = self.ingTree.get_model()
        iter = store.get_iter(path)
        ing=self.selectedIng()
        if head==_('Shopping Category'):
            self.rg.sl.orgdic[ing.ingkey]=text
            store.set_value(iter, colnum, text)
        elif type(ing) == str:
            debug('Changing group to %s'%text,2)
            self.change_group(iter, text)
            return            
        else:
            attr=self.head_to_att[head]
            if attr=='amount':
                if type(store.get_value(iter,0)) != type(""):
                    # if we're not a group
                    d={}
                    try:
                        d['amount'],d['rangeamount']=parse_range(text)
                    except:
                        show_amount_error(text)
            else:
                d={attr:text}
                if attr=='unit':
                    amt,msg=self.changeUnit(d['unit'],ing)
                    if amt:
                        d['amount']=amt
                    if msg: self.message(msg)
                elif attr=='item':
                    d['ingkey']=self.rg.rd.km.get_key(d['item'])
            debug('undoable_modify_ing %s'%d,0)
            self.rg.rd.undoable_modify_ing(
                ing,d,self.history,
                make_visible = lambda ing,dic: self.showIngredientChange(iter,dic)
                )

    def showIngredientChange (self, iter, d):
        d=d.copy()
        # we hackishly muck up the dictionary so that the 'amount' field
        # becomes the proper display amount.
        if d.has_key('amount'):
            d['amount']=convert.float_to_frac(d['amount'])
        if d.has_key('rangeamount'):
            if d['rangeamount']:
                d['amount']=d['amount']+'-'+convert.float_to_frac(d['rangeamount'])
            del d['rangeamount']
        self.resetIngredients()
        if d.has_key('ingkey'):
            ## if the key has been changed and the shopping category is not set...
            ## COLUMN NUMBER FOR Shopping Category==6
            shopval=self.imodel.get_value(iter, 6)
            debug('Shopping Category value was %s'%shopval,4)
            if shopval:
                self.rg.sl.orgdic[d['ingkey']]=shopval
            else:
                if self.rg.sl.orgdic.has_key(d['ingkey']):
                    debug('Setting new shopping category!',2)
                    self.imodel.set_value(iter, 6, self.rg.sl.orgdic[d['ingkey']])
        for attr,v in d.items():
            if self.ingColsByAttr.has_key(attr):
                self.imodel.set_value(iter,self.ingColsByAttr[attr],v)

    def changeUnit (self, new_unit, ing):
        """Handed a new unit and an ingredient, we decide whether to convert and return:
        None (don't convert) or Amount (new amount)
        Message (message for our user) or None (no message for our user)"""
        key=ing.ingkey
        old_unit=ing.unit
        old_amt=ing.amount        
        density=None
        conversion = self.rg.conv.converter(old_unit,new_unit,key)
        if conversion and conversion != 1:
            new_amt = old_amt*conversion
            opt1 = _("Converted: %(amt)s %(unit)s")%{'amt':convert.float_to_frac(new_amt),
                                                     'unit':new_unit}
            opt2 = _("Not Converted: %(amt)s %(unit)s")%{'amt':convert.float_to_frac(old_amt),
                                                         'unit':new_unit}
            CONVERT = 1
            DONT_CONVERT = 2
            choice = de.getRadio(label=_('Changed unit.'),
                                 sublabel=_('You have changed the unit for %(item)s from %(old)s to %(new)s. Would you like the amount converted or not?')%{
                'item':ing.item,
                'old':old_unit,
                'new':new_unit},
                                 options=[(opt1,CONVERT),
                                          (opt2,DONT_CONVERT),]
                                 )
            if not choice:
                raise "User cancelled"
            if choice==CONVERT:
                return (new_amt,
                        _("Converted %(old_amt)s %(old_unit)s to %(new_amt)s %(new_unit)s"%{
                    'old_amt':old_amt,
                    'old_unit':old_unit,
                    'new_amt':new_amt,
                    'new_unit':new_unit,})
                        )
            else:
                return (None,
                        None)
        if conversion:
            return (None,None)
        return (None,
                _("Unable to convert from %(old_unit)s to %(new_unit)s"%{'old_unit':old_unit,
                                                                         'new_unit':new_unit}
                  ))
                    
    def dragIngsRecCB (self, widget, context, x, y, selection, targetType,
                         time):
        debug("dragIngsRecCB (self=%s, widget=%s, context=%s, x=%s, y=%s, selection=%s, targetType=%s, time=%s)"%(self, widget, context, x, y, selection, targetType, time),3)
        drop_info=self.ingTree.get_dest_row_at_pos(x,y)
        mod=self.ingTree.get_model()
        if drop_info:
            path, position = drop_info
            diter = mod.get_iter(path)
            dest_ing=mod.get_value(diter,0)
            if type(dest_ing)==type(""): group=True
            else: group=False
            debug('drop_info good, GROUP=%s'%group,5)
            #new_iter=mod.append(None)
            #path=mod.get_path(new_iter)
        else:
            diter = None
            group = False
            position = None
        #self.pre_modify_tree()            
        if str(selection.target) == 'GOURMET_INTERNAL':
               # if this is ours, we move it
               self.selected_iter.reverse() # all things must go backwards in treeView land...
               if (group and
                   (position==gtk.TREE_VIEW_DROP_INTO_OR_BEFORE
                    or
                    position==gtk.TREE_VIEW_DROP_INTO_OR_AFTER)
                   ):
                   self.pre_modify_tree()
                   for i in self.selected_iter:
                       te.move_iter(mod,i,sibling=diter,direction="before",parent=diter)
                   self.post_modify_tree()
               elif (position==gtk.TREE_VIEW_DROP_INTO_OR_BEFORE
                     or
                     position==gtk.TREE_VIEW_DROP_BEFORE):
                   self.pre_modify_tree()
                   for i in self.selected_iter:
                       te.move_iter(mod,i,sibling=diter,direction="before")
                   self.post_modify_tree()
               else:
                   self.pre_modify_tree()
                   for i in self.selected_iter:
                       te.move_iter(mod,i,sibling=diter,direction="after")
                   self.post_modify_tree()                       
               #self.ingTree.get_selection().select_iter(new_iter)
        else:
            # if this is external, we copy
            debug('external drag!',2)
            for l in selection.data.split("\n"):
                self.add_ingredient_from_line(l)
        self.commit_positions()
        debug("restoring selections.")
        #self.post_modify_tree()
        debug("done restoring selections.")        

    def add_ingredient_from_line (self, line):
        """Add an ingredient to our list from a line of plain text"""
        d=self.rg.rd.ingredient_parser(line, conv=self.rg.conv)
        self.pre_modify_tree()
        if d:
            d['id']=self.current_rec.id
            i=self.rg.rd.add_ing(d)
            iter=self.add_ingredient(self.imodel,i,self.mult)
            self.ss.add_selection(iter)
        self.post_modify_tree()

    def pre_modify_tree (self):
        """This shouldn't really be necessary, but I'm getting
        a lot of bizarre behavior and segfaults from modifying
        the tree while connected.
        So, this should be called before adding, deleting or
        moving rows in our model"""
        debug('pre_modify_tree called',5)
        self.ss = te.selectionSaver(self.ingTree)
        debug('disconnecting tree')
        self.ingTree.set_model(empty_model)
        debug('pre_modify_tree done')

    def post_modify_tree (self):
        """And this must be called after adding, deleting or
        moving rows in our model."""
        debug('post_modify_tree called')
        self.ingTree.set_model(self.imodel)
        debug('expanding all')        
        self.ingTree.expand_all()
        debug('restoring selections')                
        self.ss.restore_selections()
        debug('post_modify_tree done')

    def commit_positions (self):
        debug("Committing positions",4)
        iter=self.imodel.get_iter_first()
        self.edited=True
        n=0
        def commit_iter(iter,pos,group=None):
            debug("iter=%s,pos=%s,group=%s"%(iter,pos,group),-1)
            ing=self.imodel.get_value(iter,0)
            if type(ing)==type(""):
                group=self.imodel.get_value(iter,1)
                i=self.imodel.iter_children(iter)
                while i:
                    pos=commit_iter(i,pos,group)
                    i=self.imodel.iter_next(i)
            else:
                #ing.position=pos
                #if group:
                #    debug('adding ingredient to group %s'%group,-1)
                #    #self.rg.rd.modify_ing(ing,{'inggroup':group})
                #    #ing.inggroup=group
                self.rg.rd.modify_ing(ing,
                                      {'position':pos,
                                       'inggroup':group,}
                                       )
                pos+=1
            return pos
        while iter:
            n=commit_iter(iter,n)
            iter=self.imodel.iter_next(iter)
            debug("Next iter = %s"%iter)
        self.resetIngredients()
        self.message(_('Changes to ingredients saved automatically.'))
        debug("Done committing positions",4)

    def dragIngsGetCB (self, tv, context, selection, info, timestamp):
        def grab_selection (model, path, iter, args):
            strings, iters = args            
            str = ""
            amt = model.get_value(iter,1)
            if amt:
                str="%s "%amt
            unit = model.get_value(iter,2)
            if unit:
                str="%s%s "%(str,unit)
            item = model.get_value(iter,3)
            if item:
                str="%s%s"%(str,item)
            debug("Dragged string: %s, iter: %s"%(str,iter),3)
            iters.append(iter)
            strings.append(str)
        strings=[]
        iters=[]
        tv.get_selection().selected_foreach(grab_selection,(strings,iters))
        str=string.join(strings,"\n")
        selection.set('text/plain',0,str)
        selection.set('STRING',0,str)
        selection.set('GOURMET_INTERNAL',8,'blarg')
        self.selected_iter=iters
        

    def selectedIng (self):
        debug("selectedIng (self):",5)
        path, col = self.ingTree.get_cursor()
        if path:
            itera = self.ingTree.get_model().get_iter(path)
        else:
            tv,rows = self.ingTree.get_selection().get_selected_rows()
            if len(rows) > 0:
                itera = rows[0]
            else:
                itera=None
        if itera: return self.ingTree.get_model().get_value(itera,0)
        else: return None

    def ingTreeClickCB (self, tv, path, col, p=None):
        debug("ingTreeClickCB (self, tv, path, col, p=None):",5)
        i=self.selectedIng()
        if hasattr(i,'refid') and i.refid:
            rec=self.rg.rd.get_referenced_rec(i)
            if rec:
                self.rg.openRecCard(rec)
            else:
                
                de.show_message(parent=self.widget, label=_("The recipe %s (ID %s) is not in our database.")%(i.item,
                                                                                                           i.refid))
        else: self.ie.show(self.selectedIng())

    def create_imodel (self, rec, mult=1):
        debug("create_imodel (self, rec, mult=1):",5)
        self.current_rec=rec
        ings=self.rg.rd.get_ings(rec)
        # as long as we have the list here, this is a good place to update
        # the activity of our menuitem for forgetting remembered optionals        
        remembered=False
        for i in ings:
            if i.shopoptional==1 or i.shopoptional==2:
                remembered=True
                break
        self.forget_remembered_optionals_menuitem = self.glade.get_widget('forget_remembered_optionals_menuitem')
        self.forget_remembered_optionals_menuitem.set_sensitive(remembered)
        ## now we continue with our regular business...
        debug("%s ings"%len(ings),3)
        self.ing_alist=self.rg.rd.order_ings(ings)
        model = gtk.TreeStore(gobject.TYPE_PYOBJECT,
                              gobject.TYPE_STRING,
                              gobject.TYPE_STRING,
                              gobject.TYPE_STRING,
                              gobject.TYPE_BOOLEAN,
                              gobject.TYPE_STRING,
                              gobject.TYPE_STRING)
        for g,ings in self.ing_alist:
            if g:
                g=self.add_group(g,model)
            for i in ings:
                debug('adding ingredient %s'%i.item,0)
                self.add_ingredient(model, i, mult, g)
        return model

    def add_group (self, name, model, prev_iter=None, children_iters=[]):
        debug('add_group',5)
        if not prev_iter:
            groupiter = model.append(None)
        else:
            groupiter = model.insert_after(None,prev_iter,None)
        model.set_value(groupiter, 0, "GROUP %s"%name)
        model.set_value(groupiter, 1, name)
        for c in children_iters: 
            te.move_iter(model,c,None,parent=groupiter,direction='after')
            #self.rg.rd.undoable_modify_ing(model.get_value(c,0),
            #                               {'inggroup':name},
            #                               self.history)
        debug('add_group returning %s'%groupiter,5)
        return groupiter

    def change_group (self, iter, text):
        debug('Undoable group change: %s %s'%(iter,text),3)
        model = self.ingTree.get_model()
        oldgroup0 = model.get_value(iter,0)
        oldgroup1 = model.get_value(iter,1)
        def change_my_group ():
            model.set_value(iter,0,"GROUP %s"%text)
            model.set_value(iter,1,text)
            self.commit_positions()
        def unchange_my_group ():
            model.set_value(iter,0,oldgroup0)
            model.set_value(iter,1,oldgroup1)
            self.commit_positions()
        obj = Undo.UndoableObject(change_my_group,unchange_my_group,self.history)
        obj.perform()

    def add_ingredient (self, model, ing, mult, group_iter=None):
        """group_iter is an iter to put our ingredient inside of.
        If group_iter is not a group but an ingredient, we'll insert our
        ingredient after it"""
        debug("add_ingredient (self=%s, model=%s, ing=%s, mult=%s, group_iter=%s):"%(self, model, ing, mult, group_iter),5)
        i = ing
        if group_iter:
            if type(model.get_value(group_iter, 0))==type(""):
                debug("Adding to group",4)
                iter = model.append(group_iter)
            else:
                iter = model.insert_after(None, group_iter, None)
                debug("Adding after iter",5)            
        else:
            iter = model.insert_before(None, None, None)
        #amt,unit = self.make_readable_amt_unit(i)
        amt = self.rg.rd.get_amount_as_string(i)
        unit = i.unit
        model.set_value(iter, 0, i)
        model.set_value(iter, 1, amt)
        model.set_value(iter, 2, unit)
        model.set_value(iter, 3, i.item)
        if i.optional:
            opt=True
        else:
            opt=False
        model.set_value(iter, 4, opt)
        model.set_value(iter, 5, i.ingkey)
        if self.rg.sl.orgdic.has_key(i.ingkey):
            debug("Key %s has category %s"%(i.ingkey,self.rg.sl.orgdic[i.ingkey]),5)
            model.set_value(iter, 6, self.rg.sl.orgdic[i.ingkey])
        else:
            model.set_value(iter, 6, None)
        return iter

    def make_readable_amt_unit (self, i):
        """Handed an ingredient, return a readable amount and unit."""
        return self.rg.rd.get_amount_and_unit(i,
                                              mult=self.mult,
                                              conv=self.rg.conv
                                              )
        
    def importIngredientsCB (self, *args):
        debug('importIngredientsCB',5) #FIXME
        f=de.select_file(_("Choose a file containing your ingredient list."),action=gtk.FILE_CHOOSER_ACTION_OPEN)
        self.importIngredients(f)

    def pasteIngsCB (self, *args):
        debug('paste ings cb')
        if not hasattr(self,'cb'):
            self.cb = gtk.clipboard_get(gtk.gdk.SELECTION_PRIMARY)
        def add_ings_from_clippy (cb,txt,data):
            if txt:
                for l in txt.split('\n'):
                    if l.strip(): self.add_ingredient_from_line(l)
            self.resetIngredients()
            self.message(_('Changes to ingredients saved automatically.'))
        self.cb.request_text(add_ings_from_clippy)

    def editCB (self, button):
        #for k,v in self.notebook_pages.items():
        #    if v=='attributes':
        self.setEditMode(button.get_active())
            
    def setEditMode (self, edit_on):
        if edit_on:
            self.notebook.set_show_tabs(True)
            self.undoButtons.set_visible(True)
            self.saveButtons.set_visible(True)
            self.notebook.set_current_page(self.NOTEBOOK_ATTR_PAGE)
        else:
            self.notebook.set_show_tabs(False)
            self.undoButtons.set_visible(False)
            self.saveButtons.set_visible(False)            
            self.notebook.set_current_page(self.NOTEBOOK_DISPLAY_PAGE)

    def importIngredients (self, file):
        ifi=file(file,'r')
        for line in ifi:
            self.add_ingredient_from_line(line)
        self.resetIngredients()
        self.message(_('Changes to ingredients saved automatically.'))

    def saveAs (self, *args):
        debug("saveAs (self, *args):",5)
        opt = self.prefs.get('save_recipe_as','html')
        if opt and opt[0]=='.': opt = opt[1:] #strip off extra "." if necessary
        fn,exp_type=de.saveas_file(_("Save recipe as..."),
                                   filename="~/%s.%s"%(self.current_rec.title,opt),
                                   filters=exporters.saveas_single_filters[0:])
        if not fn: return
        if not exp_type or not exporters.exporter_dict.has_key(exp_type):
            de.show_message(_('Gourmet cannot export file of type "%s"')%os.path.splitext(fn)[1])
            return
        out=open(fn,'w')
        myexp = exporters.exporter_dict[exp_type]
        try:
            myexp['exporter']({
                'rd':self.rg.rd,
                'rec':self.current_rec,
                'out':out,
                'conv':self.rg.conv,
                'change_units':self.prefs.get('readableUnits',True),
                'mult':self.mult,
                })
            self.message(myexp['single_completed']%{'file':fn})
        except:
            from StringIO import StringIO
            f = StringIO()
            traceback.print_exc(file=f)
            error_mess = f.getvalue()
            de.show_message(
                label=_('Unable to save %s')%fn,
                sublabel=_('There was an error during export.'),
                expander=(_('_Details'),error_mess),
                message_type=gtk.MESSAGE_ERROR
                )
        # set prefs for next time
        out.close()
        ext=os.path.splitext(fn)[1]
        self.prefs['save_recipe_as']=ext

    def changedCB (self, widget):
        ## This needs to keep track of undo history...
        self.setEdited()

    def setEdited (self, boolean=True):
        debug("setEdited (self, boolean=True):",5)
        self.edited=boolean
        if boolean:
            self.applyB.set_sensitive(True)
            self.revertB.set_sensitive(True)
            self.message(_("You have unsaved changes."))
        else:
            self.applyB.set_sensitive(False)
            self.revertB.set_sensitive(False)
            self.message(_("There are no unsaved changes."))

    def hide (self, *args):
        debug("hide (self, *args):",5)
        if self.edited:
            test=de.getBoolean(label=_("Save edits to %s before closing?")%self.current_rec.title,
                               cancel_returns='CANCEL')
            if test=='CANCEL':
                
                return True
            elif test:
                self.saveEditsCB()
            else:
                self.edited=False #to avoid multiple dialogs if this gets called twice somehow
                if self.new:
                    self.delete()
                    #self.rg.rd.delete_rec(self.current_rec.id)
        # save our position
        for c in self.conf:
            c.save_properties()
        self.widget.hide()
        # delete it from main apps list of open windows
        self.rg.del_rc(self.current_rec.id)
        #return True
        # now we destroy old recipe cards
        
    def show (self, *args):
        debug("show (self, *args):",5)
        self.widget.show()
        try:
            self.widget.set_title("%s %s"%(self.default_title,self.current_rec.title))
            self.widget.present()
        except:
            self.widget.grab_focus()

    def email_rec (self, *args):
        if self.edited:
            if de.getBoolean(label=_("You have unsaved changes."),
                             sublabel=_("Apply changes before e-mailing?")):
                self.saveEditsCB()
        from exporters import recipe_emailer
        d=recipe_emailer.EmailerDialog([self.current_rec],
                                       self.rg.rd, self.prefs, self.rg.conv)
        d.setup_dialog()
        d.email()

    def print_rec (self, *args):
        if self.edited:
            if de.getBoolean(label=_("You have unsaved changes."),
                             sublabel=_("Apply changes before printing?")):
                self.saveEditsCB()
        printer.RecRenderer(self.rg.rd, [self.current_rec], mult=self.mult,
                            dialog_title=_("Print Recipe %s"%(self.current_rec.title)),
                            dialog_parent=self.widget,
                            change_units=self.prefs.get('readableUnits',True)
                            )

    def message (self, msg):
        debug('message (self, msg): %s'%msg,5)
        self.stat.push(self.contid,msg)

class ImageBox:
    def __init__ (self, RecCard):
        debug("__init__ (self, RecCard):",5)
        self.rg = RecCard.rg
        self.rc = RecCard
        self.glade = self.rc.glade
        self.imageW = self.glade.get_widget('recImage')
        self.addW = self.glade.get_widget('addImage')
        self.delW = self.glade.get_widget('delImageButton')
        self.imageD = self.glade.get_widget('imageDisplay')
        self.image = None
        changed=False

    def get_image (self, rec=None):
        debug("get_image (self, rec=None):",5)
        if not rec:
            rec=self.rc.current_rec
        if rec.image:
            self.set_from_string(rec.image)
        else:
            self.image=None
            self.hide()

    def hide (self):
        debug("hide (self):",5)
        self.imageW.hide()
        self.delW.hide()
        self.addW.show()
        return True
        
    def commit (self):
        debug("commit (self):",5)
        """Put current image in database"""
        if self.image:
            ofi = StringIO.StringIO()
            self.image.save(ofi,"JPEG")
            self.rc.current_rec.image=ofi.getvalue()
            ofi.close()
            ofi = StringIO.StringIO()
            self.thumb.save(ofi,"JPEG")
            self.rc.current_rec.thumb=ofi.getvalue()
            ofi.close()
        else:
            self.rc.current_rec.image=""
            self.rc.current_rec.thumb=""
    
    def draw_image (self):
        debug("draw_image (self):",5)
        """Put image onto widget"""
        if self.image:
            self.win = self.imageW.get_parent_window()
            if self.win:
                wwidth,wheight=self.win.get_size()
                wwidth=int(float(wwidth)/3)
                wheight=int(float(wheight)/3)
            else:
                wwidth,wheight=100,100
            self.image=ie.resize_image(self.image,wwidth,wheight)
            self.thumb=ie.resize_image(self.image,40,40)
            file = StringIO.StringIO()            
            self.image.save(file,'JPEG')
            self.set_from_string(file.getvalue())
            file.close()
        else:
            self.hide()

    def show_image (self):
        debug("show_image (self):",5)
        """Show widget and switch around buttons sensibly"""
        self.addW.hide()
        self.imageW.show()
        self.delW.show()

    def set_from_string (self, string):
        debug("set_from_string (self, string):",5)
        pb=ie.get_pixbuf_from_jpg(string)
        self.imageW.set_from_pixbuf(pb)
        self.imageD.set_from_pixbuf(pb)
        self.show_image()

    def set_from_file (self, file):
        debug("set_from_file (self, file):",5)
        self.image = Image.open(file)
        self.draw_image()        
        
    def set_from_fileCB (self, *args):
        debug("set_from_fileCB (self, *args):",5)
        f=de.select_image("Select Image",action=gtk.FILE_CHOOSER_ACTION_OPEN)
        if f:
            self.set_from_file(f)
            self.rc.setEdited(True)
            self.edited=True

    def removeCB (self, *args):
        debug("removeCB (self, *args):",5)
        if de.getBoolean(label="Are you sure you want to remove this image?",
                         parent=self.rc.widget):
            self.rc.current_rec.image=''
            self.image=None
            self.draw_image()
            self.edited=True
            self.rc.setEdited(True)

# Our ingredient editor has some focus trickiness... here's some
# convenience functions to mess with that.
# (NOT WORKING YET!)
# def adjust_focus (widget,
#                   before=None,
#                   after=None):
#     widget.before = before
#     widget.after = after
    
#     def key_press_cb (w,event):
#         name = gtk.gdk.keyval_name(event.keyval)
#         w.keyname = name
        
#     def focus_out_cb (w,event):
#         if hasattr(w,'keyname'):
#             name = w.keyname
#         if name in ['Tab','tab']:
#             if widget.after:
#                 print 'grabbing focus for ',widget.after                
#                 #if isinstance(widget.after,gtk.Entry): widget.after.insert_text('Hello')
#                 #widget.emit_stop_by_name('focus-out-event')
#                 def grab_next_focus ():
#                     print 'really grabbing focus for ',widget.after
#                     widget.after.grab_focus()
#                 gobject.timeout_add(1,grab_next_focus)
#                 #return True
#             #elif name in ['blarg']:
#             else:
#                 if widget.before:
#                     print 'grabbing focus for ',widget.before
#                     #if isinstance(widget,gtk.Entry): widget.before.insert_text('Hello')
#                     widget.before.grab_focus()
#                     #widget.emit_stop_by_name('focus-out-event')
#                     #return True
#     widget.connect('key-press-event',key_press_cb)
#     #widget.connect('focus-out-event',focus_out_cb)
#     widget.connect('key-press-event',focus_out_cb)
            
class IngredientEditor:
    def __init__ (self, RecGui, rc):
        debug("IngredientEditor.__init__ (self, RecGui):",5)
        self.ing = None
        self.user_set_key=False
        self.user_set_shopper=False
        self.rc=rc
        self.rg = RecGui
        self.init_dics()
        self.myLastKeys = None
        self.setup_glade()
        self.setup_comboboxen()
        self.setup_signals()
        self.last_ing = ""

    def init_dics (self):
        self.orgdic = self.rg.sl.sh.orgdic
        self.shopcats = self.rg.sl.sh.get_orgcats()        
        
    def setup_comboboxen (self):
        # setup combo box for unitbox
        debug('start setup_comboboxen()',3)
        self.unitBox.set_model(self.rg.umodel)        
        if len(self.rg.umodel) > 6:
            self.unitBox.set_wrap_width(2)
            if len(self.rg.umodel) > 10:
                self.unitBox.set_wrap_width(3)
        self.unitBox.set_text_column(0)
        cb.FocusFixer(self.unitBox)
        # remove this temporarily because of annoying gtk bug
        # http://bugzilla.gnome.org/show_bug.cgi?id=312528
        self.unitBox.entry = self.unitBox.get_children()[0]
        #cb.setup_completion(self.unitBox) # add autocompletion

        # setup combo box for keybox
        def setup_keybox (model):
            self.keyBox.set_model(model.filter_new())        
            self.keyBox.set_text_column(0)
            if len(model) > 5:
                self.keyBox.set_wrap_width(3)
                
        setup_keybox(self.rg.inginfo.key_model)
        self.rg.inginfo.disconnect_calls.append(lambda *args: self.keyBox.set_model(empty_model))
        self.rg.inginfo.key_connect_calls.append(setup_keybox)
        cb.setup_completion(self.keyBox) #add autocompletion
        cb.FocusFixer(self.keyBox)
        # add autocompletion for items
        if hasattr(self,'ingBox'):
            cb.make_completion(self.ingBox, self.rg.inginfo.item_model)
            self.rg.inginfo.disconnect_calls.append(self.ingBox.get_completion().set_model(empty_model))
            self.rg.inginfo.item_connect_calls.append(lambda m: self.ingBox.get_completion().set_model(m))
        cb.set_model_from_list(self.shopBox,self.shopcats)
        cb.setup_completion(self.shopBox)
        cb.FocusFixer(self.shopBox)
        if len(self.shopBox.get_model()) > 5:
            self.shopBox.set_wrap_width(2)
            if len (self.shopBox.get_model()) > 10:
                self.shopBox.set_wrap_width(3)
        self.new()
        
    def setup_glade (self):
        self.glade=self.rc.glade
        #self.glade.signal_connect('ieKeySet', self.keySet)
        #self.glade.signal_connect('ieShopSet', self.shopSet)
        #self.glade.signal_connect('ieApply', self.apply)
        self.ieBox = self.glade.get_widget('ieBox')
        self.ieExpander = self.glade.get_widget('ieExpander')
        #self.ieBox.hide()
        self.amountBox = self.glade.get_widget('ieAmount')
        self.unitBox = self.glade.get_widget('ieUnit')
        self.keyBox = self.glade.get_widget('ieKey')
        self.ingBox = self.glade.get_widget('ieIng')
        self.shopBox = self.glade.get_widget('ieShopCat')
        self.optCheck = self.glade.get_widget('ieOptional')
        self.togWidget = self.glade.get_widget('ieTogButton')
        self.quickEntry = self.glade.get_widget('quickIngredientEntry')
        
    def setup_signals (self):
        self.glade.signal_connect('ieAdd', self.add)
        self.glade.signal_connect('ieNew', self.new)
        self.glade.signal_connect('addQuickIngredient',self.quick_add)
        #self.glade.signal_connect('ieDel', self.delete_cb)        
        if hasattr(self,'ingBox') and self.ingBox:
            self.ingBox.connect('focus_out_event',self.setKey)
            self.ingBox.connect('editing_done',self.setKey)
        if hasattr(self,'keyBox') and self.keyBox:
            self.keyBox.connect('changed',self.keySet)
            self.keyBox.get_children()[0].connect('changed',self.keySet)
        if hasattr(self,'shopBox'):            
            self.shopBox.connect('changed',self.shopSet)
        # now we connect the activate signal manually that makes
        # hitting "return" add the ingredient. This way if we think
        # we were trying to autocomplete, we can block this signal.
        for w in ['ingBox','shopBox','keyBox']:
            if hasattr(self,w) and getattr(self,w):
                widg = getattr(self,w)
                if type(widg) == gtk.ComboBoxEntry:
                    widg = widg.get_children()[0]
                if type(widg) == gtk.Entry:
                    widg.connect('activate',self.add)

    def keySet (self, *args):
        debug("keySet (self, *args):",0)
        if not re.match("^\s*$",self.keyBox.entry.get_text()):
            debug('user set key',0)
            self.user_set_key=True
            self.setShopper()
        else:
            debug('user unset key',0)
            #if user blanks key, we do our automagic again            
            self.user_set_key=False 

    def shopSet (self, *args):
        if not re.match("^\s*$",self.shopBox.entry.get_text()):
            self.user_set_shopper=True
        else:
            #if user blanks key, we do our automagic again
            self.user_set_key=False

    def addKey (self,key,item):
        debug("addKey (self,key,item):",5)
        pass
        # this stuff is no longer necessary
        # with our new key dictionary class
        #
        #if self.keydic.has_key(item):
        #    self.keydic[item].append(key)
        #else:
        #    self.keydic[item]=[key]
    
    def getKey (self):
        debug("getKey (self):        ",5)
        kk=self.keyBox.entry.get_text()
        if kk:
            return kk
        else:
            #return self.myKeys[0]
            return ""
        
    def getKeyList (self, ing=None):
        debug("getKeyList (self):",5)
        if not ing:
            ing = self.ingBox.get_text()
        return self.rg.rd.key_search(ing)

    def setKey (self, *args):
        debug("setKeyList (self, *args):        ",5)
        ing =  self.ingBox.get_text()
        if ing == self.last_ing:
            return
        myKeys = self.getKeyList(ing)
        if myKeys and not self.user_set_key:
            self.keyBox.entry.set_text(myKeys[0])
            self.user_set_key=False
        # and while we're at it...
        self.setKeyList()
        self.setShopper()
        self.last_ing = ing

    def setKeyList (self, *args):
        debug('setKeyList called!',0)
        t=TimeAction('getKeyList()',0)
        self.myKeys = self.getKeyList()
        t.end()
        self.itxt = self.ingBox.get_text()
        t=TimeAction('keybox - rebuild model',0)
        model = gtk.ListStore(str)
        for k in self.myKeys: model.append([k])
        self.keyBox.set_model(model)
        #self.keyBox.get_model().refilter()
        t.end()
        if len(self.keyBox.get_model()) > 6:
            self.keyBox.set_wrap_width(2)
            if len(self.keyBox.get_model()) > 10:
                self.keyBox.set_wrap_width(3)
        else: self.keyBox.set_wrap_width(1)
        self.myLastKeys=self.myKeys

    def setShopper (self):
        debug("setShopper (self):",5)
        if not self.user_set_shopper:
            sh = self.getShopper()
            if sh:
                self.shopBox.entry.set_text(sh)
                self.user_set_shopper=False
                
    def getShopper (self):
        debug("getShopper (self):",5)
        key = self.getKey()
        if self.orgdic.has_key(key):
            return self.orgdic[key]
        else:
            return None
                         
    def show (self, ing):
        debug("show (self, ing):",5)
        self.ing = ing
        if hasattr(ing,'item'):
            self.ingBox.set_text(ing.item)
        if hasattr(ing,'ingkey'):
            self.keyBox.entry.set_text(ing.ingkey)
            self.keyBox.entry.user_set_key=True
        else:
            self.user_set_key=False            
        if hasattr(ing,'amount'):
            self.amountBox.set_text(
                self.rg.rd.get_amount_as_string(ing)
                )
        if hasattr(ing,'unit'):
            self.unitBox.entry.set_text(ing.unit)
        if hasattr(ing,'optional') and ing.optional:
            self.optCheck.set_active(True)
        else:
            self.optCheck.set_active(False)
        self.user_set_shopper=False
        self.getShopper()

    def new (self, *args):
        debug("new (self, *args):",5)
        self.ing = None
        self.unitBox.entry.set_text("")
        self.shopBox.entry.set_text("")
        self.amountBox.set_text("")
        if hasattr(self,'ingBox') and self.ingBox:
            self.ingBox.set_text("")
        self.keyBox.entry.set_text("")
        self.user_set_key=False
        self.user_set_shopper=False
        if hasattr(self,'optCheck') and self.optCheck:
            self.optCheck.set_active(False)
        self.amountBox.grab_focus()

    def quick_add (self, *args):
        txt = self.quickEntry.get_text()
        self.rc.add_ingredient_from_line(txt)
        self.quickEntry.set_text('')
        self.rc.resetIngredients()
        self.rc.message(_('Changes to ingredients saved automatically.'))

    def add (self, *args):
        debug("add (self, *args):",5)
        d = {}
        d['id']=self.rc.current_rec.id
        d['ingkey']=self.getKey()
        d['item']=self.ingBox.get_text()
        d['unit']=self.unitBox.entry.get_text()
        amt=self.amountBox.get_text()
        if amt:
            try:
                d['amount'],d['rangeamount']= parse_range(amt)
            except:
                show_amount_error(amt)
                raise
        if not d['item'] :
            # if there's no item but there is a key, we assume that the user
            # wanted the item to be the same as the key
            if d['ingkey']:
                d['item']=d['item']
                self.rc.message(_('Assuming you wanted item equal to key %s')%d['ingkey'])
            # if there's not an item or a key, we check if our user
            # made a typing error and meant the unit as an item
            elif d['unit'] and not d['unit'] in self.rg.conv.units:
                itm = d['unit']
                d['item']=d['unit']
                d['unit']=""
                self.rc.message(_('You forgot an item. Assuming you meant "%s" as an item and not a unit.')%itm)
            else:
                self.rc.message(_('An ingredient must have an item!'))
                return
        if self.optCheck.get_active(): d['optional']=True
        else: d['optional']=False
        if not d['ingkey']:
            #print 'grabbing key...'
            d['ingkey']=self.rg.rd.km.get_key(d['item'])
        sh = self.shopBox.entry.get_text()
        if sh:
            self.rg.sl.sh.add_org_itm(d['ingkey'],sh)
        if self.ing:
            debug('Do modify ing',5)
            i=self.rg.rd.undoable_modify_ing(self.ing,d,self.rc.history)
            debug('modified ing',5)
            debug('resetting inglist',5)
            self.rc.resetIngredients()
            debug('reset inglist',5)
        else:
            debug('Do rg.rd.add_ing',5)
            i=self.rg.rd.add_ing(d)
            debug('add ingredient to view',5)
            iter=self.rc.add_ingredient(self.rc.imodel,i,self.rc.mult,
                                        group_iter=self.rc.getSelectedIter())
            debug('added ing to view',5)
            debug('select iter',5)
            path=self.rc.imodel.get_path(iter)
            self.rc.ingTree.expand_to_path(path)
            self.rc.ingTree.get_selection().select_iter(iter)
            debug('selected iter',5)
        debug('blank selves/new',5)
        self.new()
        debug('done!',5)
        self.rc.resetIngList()
        self.rc.message(_('Changes to ingredients saved automatically.'))            
        #self.new()

    def delete_cb (self, *args):
        debug("delete_cb (self, *args):",5)
        mod,rows = self.rc.ingTree.get_selection().get_selected_rows()
        rows.reverse()
        ings_to_delete = []
        for p in rows:
            i=mod.get_iter(p)
            ing = mod.get_value(i,0)
            if type(ing) == type(""):
                ## then we're a group
                self.remove_group(i)
            #elif de.getBoolean(label=_("Are you sure you want to delete %s?")%ing.item):
            else:
                ings_to_delete.append(ing)
        print 'undoable_delete_ings(',ings_to_delete
        self.rg.rd.undoable_delete_ings(ings_to_delete, self.rc.history,
                                        make_visible=lambda *args: self.rc.resetIngList())
        #self.new()
                                      
    def remove_group (self, iter):
        nchildren = self.rc.imodel.iter_n_children(iter)
        group = self.rc.imodel.get_value(iter,1)
        if type(nchildren) != type(1):
            # if there are no children
            # we just remove the group
            # heading without asking
            # for confirmation
            Undo.UndoableObject(lambda *args: self.rc.imodel.remove(iter),
                                lambda *args: self.rc.add_group(group,self.rc.imodel),
                                self.rc.history)
            return
        # otherwise, we'll need to be more thorough...

        if de.getBoolean(label=_("Are you sure you want to delete %s")%group):
            # collect our childrenp
            children = []
            ings = []
            for n in range(nchildren):
                child=self.rc.imodel.iter_nth_child(iter,n)
                children.append(child)
                i=self.rc.imodel.get_value(child,0)
                ings.append([i.amount,i.unit,i.item])
            if children:
                num_of_children = len(children)
                question=ngettext(
                    "Shall I delete the item contained in %s or move it out of the group?",
                    "Shall I delete the items contained in %s or just move them out of the group?",
                    num_of_children
                    )%group
                tree = te.QuickTree(ings, [_("Amount"),_("Unit"),_("Item")])
                debug("de.getBoolean called with:")
                debug("label=%s"%question)
                debug("expander=['See ingredients',%s]"%tree)
                delete=de.getBoolean(label=question,
                                     custom_yes=ngettext("Delete it.","Delete them.",num_of_children),
                                     custom_no=ngettext("Move it.","Move them.",num_of_children),
                                     expander=[_("See ingredients"),tree])
                # then we're deleting them, this is easy!
                children.reverse()
                self.rc.pre_modify_tree()
                ings_to_delete = []
                ings_to_modify = []
                for c in children:
                    ing = self.rc.imodel.get_value(c,0)
                    if delete:
                        self.rc.imodel.remove(c)
                        #self.rg.rd.delete_ing(ing)
                        ings_to_delete.append(ing)
                    else:
                        #ing.inggroup = None
                        ings_to_modify.append(ing)
                        te.move_iter(self.rc.imodel, c,
                                     sibling=iter, direction="after")
                if ings_to_delete:
                    self.rg.rd.undoable_delete_ings(ings_to_delete,self.rc.history,
                                                    make_visible=lambda *args: self.rc.resetIngList())
                if ings_to_modify:
                    def ungroup(*args):
                        debug('ungroup ingredients!',3)
                        for i in ings_to_modify:
                            self.rg.rd.modify_ing(i,{'inggroup':''})
                        self.rc.resetIngredients()
                        self.rc.resetIngList()
                    def regroup(*args):
                        debug('Unmodifying ingredients',3)
                        for i in ings_to_modify:
                            self.rg.rd.modify_ing(i,{'inggroup':group})
                        self.rc.resetIngredients()
                        self.rc.resetIngList()
                    debug('Modifying ingredients',0)
                    um=Undo.UndoableObject(ungroup,regroup,self.rc.history)                    
                    um.perform()                    
            else: self.rc.pre_modify_tree()
            self.rc.imodel.remove(iter)
            self.rc.post_modify_tree()

class IngInfo:
    """Keep models for autocompletion, comboboxes, and other
    functions that might want to access a complete list of keys,
    items and the like"""

    def __init__ (self, rd):
        self.rd = rd
        self.make_item_model()
        self.make_key_model()
        # this is a little bit silly... but, because of recent bugginess...
        # we'll have to do it. disable and enable calls are methods that
        # get called to disable and enable our models while adding to them
        # en masse. disable calls get no arguments passed, enable get args.
        self.disconnect_calls = []
        self.key_connect_calls = []
        self.item_connect_calls = []
        self.manually = False
        self.rd.add_ing_hooks.append(self.add_ing)

    def make_item_model(self):
        #unique_item_vw = self.rd.iview_not_deleted.counts(self.rd.iview_not_deleted.item, 'count')
        self.item_model = gtk.ListStore(str)
        for i in self.rd.get_unique_values('item',table=self.rd.iview,deleted=False):
            self.item_model.append([i])
        if len(self.item_model)==0:
            import defaults
            for i,k,c in defaults.lang.INGREDIENT_DATA:
                self.item_model.append([i])
        
    def make_key_model (self):
        #unique_key_vw = self.rd.iview_not_deleted.counts(self.rd.iview_not_deleted.ingkey, 'groupvw')
        # the key model by default stores a string and a list.
        self.key_model = gtk.ListStore(str)
        for k in self.rd.get_unique_values('ingkey',table=self.rd.iview,deleted=False):
            self.key_model.append([k])

    def change_key (self, old_key, new_key):
        """One of our keys has changed."""
        keys = map(lambda x: x[0], self.key_model)
        index = keys.index(old_key)
        if old_key in keys:
            if new_key in keys:
                del self.key_model[index]
            else:
                self.key_model[index]=[new_key]
        modindx = self.rd.normalizations['ingkey'].find(old_key)
        if modindx>=0:
            self.rd.normalizations['ingkey'][modindx].ingkey=new_key

    def disconnect_models (self):
        for c in self.disconnect_calls:
            if c: c()

    def connect_models (self):
        for c in self.key_connect_calls: c(self.key_model)
        for c in self.item_connect_calls: c(self.item_model)

    def disconnect_manually (self):
        self.manually = True
        self.disconnect_models()

    def reconnect_manually (self):
        self.manually=False
        self.connect_models()

    def add_ing (self, ing):
        # This is really inefficient... we're going to disable temporarily
        pass
        # if not self.manually: self.disconnect_models()
#         if hasattr(ing,'item'):
#             debug('checking for item',3)
#             if not [ing.item] in self.item_model:
#                 debug('adding item',3)                
#                 self.item_model.append([ing.item])
#                 debug('appended %s to item model'%ing.item,3)
#         if hasattr(ing,'ingkey'):
#             debug('checking for key',3)
#             if not [ing.ingkey] in self.key_model:
#                 debug('adding key',3)
#                 self.key_model.append([ing.ingkey])
#                 debug('appended %s to key model'%ing.ingkey,3)
#         debug('add ing completed',3)
#         if not self.manually: self.connect_models()

class RecSelector (RecIndex):
    """Select a recipe and add it to RecCard's ingredient list"""
    def __init__(self, RecGui, RecCard):
        self.glade=gtk.glade.XML(os.path.join(gladebase,'recSelector.glade'))
        self.glade.signal_connect('cancel',self.cancel)
        self.glade.signal_connect('ok',self.ok)        
        self.rg=RecGui
        self.reccard=RecCard
        self.dialog = self.glade.get_widget('recDialog')
        RecIndex.__init__(self,
                          self.glade,
                          self.rg.rd,
                          self.rg,
                          editable=False
                          )

    def quit (self):
        self.dialog.destroy()

    def cancel (self,*args):
        debug('cancel',0)
        self.quit()

    def ok (self,*args):
        debug('ok',0)
        pre_iter=self.reccard.getSelectedIter()
        try:
            self.reccard.pre_modify_tree()
            for rec in self.recTreeSelectedRecs():
                if rec.id == self.reccard.current_rec.id:
                    de.show_message(label=_("Recipe cannot call itself as an ingredient!"),
                                    sublabel=_('Infinite recursion is not allowed in recipes!')
                                    )
                    continue
                ingdic={'amount':1,
                        'unit':'recipe',
                        'item':rec.title,
                        'refid':rec.id,
                        'id':self.reccard.current_rec.id,}
                debug('adding ing: %s'%ingdic,5)
                i=self.rg.rd.add_ing(ingdic)
                iter=self.reccard.add_ingredient(self.reccard.imodel,i,
                                            mult=self.reccard.mult,
                                            group_iter=pre_iter)
                path=self.reccard.imodel.get_path(iter)
                self.reccard.ss.add_selection(iter)
            self.reccard.post_modify_tree()
            self.reccard.commit_positions()
            self.quit()
        except:
            de.show_message(label=_("You haven't selected any recipes!"))
            raise
        
if __name__ == '__main__':
    import GourmetRecipeManager
    import testExtras
    rg = GourmetRecipeManager.RecGui()
    RecCard(rg,rg.rd.fetch_one(rm.rview))
    gtk.main()
    
    
