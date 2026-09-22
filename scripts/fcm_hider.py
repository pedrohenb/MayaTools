"""FCM_Hider - face/component hiding tool.

Lifted verbatim out of a shelf button on the old Wildlife_Henb shelf, where all 1,319
lines lived inside the button's -command string. Only the trailing "HiderUI()" call was
removed so that importing this module does not immediately open the window.

Its UI uses string callbacks (cmds.iconTextButton(c="checkAllSets()")), which Maya
evaluates in the __main__ namespace - NOT in this module's namespace. So the launcher
has to publish these functions into __main__ before calling HiderUI(). See show().

Icons come from icons/Icons_Hider/ in this repo, resolved via XBMLANGPATH.
"""


def show():
    """Publish this module's functions into __main__, then open the UI.

    Maya resolves string-valued UI callbacks against __main__, so without this the
    buttons inside the window raise NameError.
    """
    import __main__
    namespace = globals()
    for key, value in namespace.items():
        if not key.startswith("_"):
            setattr(__main__, key, value)
    namespace["HiderUI"]()


import maya.cmds as cmds
import maya.mel as mel
import time
import subprocess

'''
# Version
versionHider = 'FCM_Hider Beta 2.2'

- support python 3
- Fixing some miss-spells in message declaration
- 

'''


# Annotations for popUp help:
allSets_Ann = 'Left Click:\n -Switch between Show and Hide set\n\nRight click options:\n- Remove all the Body sets\n- Select all content of the set\n- Remove all the Extra sets'
blueButtons_Ann = 'Left Click:\n -Switch between Show and Hide set\n\nRight click options:\n- Add your current selection to the current set\n- Remove your current selection from the current set\n- Select all content of the set\n- Remove all content from the current set'
templateLine_Ann = 'This button allows you to select the usual line between the elbow control and the pole vector control that is mostly unselectable'
editMode_Ann = 'Toggle between Usage and Edit mode'
addSel_Ann = 'Add your current selection to the current set'
addSelExtra_Ann = 'Add your current selection to the current set (Only shapes and polygons)'
grow_Ann = 'Grow selection'
shrink_Ann = 'Shrink selection'
switchPolyOrNurbsCurves_Ann = 'Left Click:\n-Switch between Poly selection and NurbsCurves\nRight Click:\n-Change poly color selection'
objectMode_Ann = 'Object Mode'
deleteAll_Ann = 'Delete everything related to the script'
help_Ann = 'Open help window'
showAllHiddenFaces_Ann = 'Show all hidden faces in the scene'
checkAllSets_Ann = 'Turn OFF and ON two times each set to check the overall setup'
mirrorButtons_Ann = 'Mirror right Arm and Leg content to the left ones'
unlockAllVisMeshes_Ann = 'Make selectable all visible meshes and unlock all layer display on the scene'
unlockAllVis_Ann = 'Make selectable all: mesh shape, nurbsCurve shape, transform, annotation shape of the scene'
lockSelection_Ann = 'Make all the items selected unselectables'
rightClickToSeeButtons_Ann = 'Right click to see the buttons'
# Prints
setsExportSucces = 'Sets exported succesfully!'
setsLoadSucces = 'Sets loaded succesfully!'
setHided = 'Set hidden'
setVisible = 'Set Visible'
allVisMeshSelectable = 'All visible meshes are selectable, and all layerDisplay are unlocked'
allBodySetsRemoved = 'All Body sets removed' 
allExtraSetsRemoved = 'All Extra sets removed'
keepYourSecrets = 'Alright then, keep your secrets' 
allRemoved = 'everything related to FCM_Hider Removed'
selRemoved = 'Selection removed'
# Warnings
allFacesAreVisible = 'All faces are visible'
setDoesntExistsSet = 'Set doesn\'t exists'
hiderSystemWarning = 'There is more than one Hider system, select the character you want to run'
confirmCheckAllSets = 'This may take a while, do you want to check them?'
nothingSel = 'Nothing selected' 
setDontExists = 'Set doesn\'t exist'
couldntUnlockAllMeshes = "Couldn't unlock all the meshes because they are in a layerDisplay, check if you can unlock them trough layer display"
couldntUnlockAllLayerDisplay = "Couldn't unlock all layerDisplay"
nothingSelected = 'Nothing selected'
# Error
errorLoadSets = 'Error trying to load the set, Try to set the namespace the same than when you export the file' 
errorExportSets = 'You can only save sets created in the scene'

# PromptWindows
removeAllConfirm = 'Are you sure you want to delete everything related to the script?'

'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                CREATE SETTINGS AND SETS
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
def declaringSets():
    global namespaceHider, All_Sets_Hider, Head_Hider, Torso_Hider, Arm_R_Hider, Arm_L_Hider, Leg_R_Hider, Leg_L_Hider, Extra_One_Hider, Extra_Two_Hider, Extra_Three_Hider, FCM_Hider_Settings
    All_Sets_Hider = ( namespaceHider + 'All_Sets_Hider' )
    Head_Hider = ( namespaceHider + 'Head_Hider' )
    Torso_Hider = ( namespaceHider + 'Torso_Hider' )
    Arm_R_Hider = ( namespaceHider + 'Arm_R_Hider' )
    Arm_L_Hider = ( namespaceHider + 'Arm_L_Hider' )
    Leg_R_Hider = ( namespaceHider + 'Leg_R_Hider' )
    Leg_L_Hider = ( namespaceHider + 'Leg_L_Hider' )
    Extra_One_Hider = ( namespaceHider + 'Extra_One_Hider' )
    Extra_Two_Hider = ( namespaceHider + 'Extra_Two_Hider' )
    Extra_Three_Hider = ( namespaceHider + 'Extra_Three_Hider' )
    FCM_Hider_Settings = ( namespaceHider + 'FCM_Hider_Settings' )
#-----------------------------------------------------------#
def createAllSets():
    global namespaceHider, All_Sets_Hider, Head_Hider, Torso_Hider, Arm_R_Hider, Arm_L_Hider, Leg_R_Hider, Leg_L_Hider, Extra_One_Hider, Extra_Two_Hider, Extra_Three_Hider, FCM_Hider_Settings
    if cmds.objExists('All_Sets_Hider') == 0:cmds.sets(n='All_Sets_Hider', em=True)
    if cmds.objExists(Head_Hider) == 0:cmds.sets(n=Head_Hider, em=True)
    if cmds.objExists(Torso_Hider) == 0:cmds.sets(n=Torso_Hider, em=True)
    if cmds.objExists(Arm_R_Hider) == 0:cmds.sets(n=Arm_R_Hider, em=True)
    if cmds.objExists(Arm_L_Hider) == 0:cmds.sets(n=Arm_L_Hider, em=True)
    if cmds.objExists(Leg_R_Hider) == 0:cmds.sets(n=Leg_R_Hider, em=True)
    if cmds.objExists(Leg_L_Hider) == 0:cmds.sets(n=Leg_L_Hider, em=True)
    if cmds.objExists(Extra_One_Hider) == 0:cmds.sets(n=Extra_One_Hider, em=True)
    if cmds.objExists(Extra_Two_Hider) == 0:cmds.sets(n=Extra_Two_Hider, em=True)
    if cmds.objExists(Extra_Three_Hider) == 0:cmds.sets(n=Extra_Three_Hider, em=True)
    # parent all sets to All_Sets_Hider
    cmds.sets (Head_Hider, Torso_Hider, Arm_R_Hider, Arm_L_Hider, Leg_R_Hider, Leg_L_Hider,
    Extra_One_Hider, Extra_Two_Hider, Extra_Three_Hider, edit=True, fe='All_Sets_Hider' )
#-----------------------------------------------------------#
def createSettingsHider():
    if cmds.objExists ('FCM_Hider_Settings') == 0:
        selCurrent = cmds.ls (sl=True)
        cmds.group (em=True, n= 'FCM_Hider_Settings')
        cmds.setAttr (".tx", lock=True, keyable=False, channelBox=False )
        cmds.setAttr (".ty", lock=True, keyable=False, channelBox=False )
        cmds.setAttr (".tz", lock=True, keyable=False, channelBox=False )
        cmds.setAttr (".rx", lock=True, keyable=False, channelBox=False )
        cmds.setAttr (".ry", lock=True, keyable=False, channelBox=False )
        cmds.setAttr (".rz", lock=True, keyable=False, channelBox=False )
        cmds.setAttr (".sx", lock=True, keyable=False, channelBox=False )
        cmds.setAttr (".sy", lock=True, keyable=False, channelBox=False )
        cmds.setAttr (".sz", lock=True, keyable=False, channelBox=False )
        cmds.setAttr (".v", lock=True, keyable=False, channelBox=False )
        # Create Attr States
        cmds.addAttr ('FCM_Hider_Settings', ln='All_Sets_Hider_State',at='bool', dv=True, keyable=True)
        cmds.addAttr ('FCM_Hider_Settings', ln='Head_Hider_State',at='bool', dv=True, keyable=True)
        cmds.addAttr ('FCM_Hider_Settings', ln='Torso_Hider_State',at='bool', dv=True, keyable=True)
        cmds.addAttr ('FCM_Hider_Settings', ln='Arm_R_Hider_State',at='bool', dv=True, keyable=True)
        cmds.addAttr ('FCM_Hider_Settings', ln='Arm_L_Hider_State',at='bool', dv=True, keyable=True)
        cmds.addAttr ('FCM_Hider_Settings', ln='Leg_L_Hider_State',at='bool', dv=True, keyable=True)
        cmds.addAttr ('FCM_Hider_Settings', ln='Leg_R_Hider_State',at='bool', dv=True, keyable=True)
        cmds.addAttr ('FCM_Hider_Settings', ln='Extra_One_Hider_State',at='bool', dv=True, keyable=True)
        cmds.addAttr ('FCM_Hider_Settings', ln='Extra_Two_Hider_State',at='bool', dv=True, keyable=True)
        cmds.addAttr ('FCM_Hider_Settings', ln='Extra_Three_Hider_State',at='bool', dv=True, keyable=True)
        # Create Attr Edit Mode
        cmds.addAttr ('FCM_Hider_Settings', ln='Edit_Mode_State',at='bool', dv=True, keyable=True)

        # Select current
        cmds.select(selCurrent)
#-----------------------------------------------------------#   
def createHiderInTheScene():
    global namespaceHider, namespaceHiderForWindow
    # nameSpace empty
    namespaceHider = ''    
    namespaceHiderForWindow = 'Created in the scene'
    # declaring sets
    declaringSets()
    # Create settings and all sets
    createSettingsHider()
    createAllSets()
    
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                    DECLARING NAMESPACES 
            
''''''''''''''''''''''''''''''''''''''''''''''''''''''''' 

def declaringNameSpaces():
    global namespaceHider, namespaceHiderForWindow
    # Check if Hider system exists and if there is more than one
    currentSel = cmds.ls(sl=True)
    if cmds.objExists('*:FCM_Hider_Settings'):
        cmds.select('*:FCM_Hider_Settings')
        try:
            cmds.select('FCM_Hider_Settings',tgl=True)
        except:
            pass    
        settings = cmds.ls(sl=True)
        
        # if there is more than one
        if len(settings) >= 1:
            try:
                # works depending selection
                try:
                    # if the selection is referenced
                    # Query nameSpace
                    namespaceHiderForWindow = cmds.referenceQuery( currentSel[0], namespace=True, shortName=True )
                    namespaceHider = namespaceHiderForWindow + ":" 
                    declaringSets()
                except:
                    createHiderInTheScene()
            except:
                cmds.warning(hiderSystemWarning)
    else:
        createHiderInTheScene()
        
    cmds.select(currentSel)


'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                PRIMARY FUNCTIONS DEF
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''

#-----------------------------------------------------------#    
def queryAllSet():
    global allSet, polys, shapes, transformAndShapeSet

    # Query all set
    allSet = cmds.sets(setHider, q=True, )
    # Query transform
    transformAndShapeSet = cmds.ls(allSet, type= [ 'transform','shape']  )
    # Query polys
    polys = cmds.filterExpand(allSet, sm=34)
    # Query meshShapes from polys
    try:
        shapes = []
        for poly in polys:
            shape = cmds.listRelatives(poly, s=True, p=True, fullPath=True)
            shapes.append(shape)
        shapes 
        def getUniqueItems(iterable):
            result = []
            for item in iterable:
                if item not in result:
                    result.append(item)
            return result
            
            print (''.join(getUniqueItems(list('apple'))))
        shapes = getUniqueItems(shapes)
    except:
        pass


#-----------------------------------------------------------#
def addSelectionToSet():
    global setHider
    try:
        sel = cmds.ls(sl=True, l=True)
        if len(sel) > 0:
            if cmds.objExists(setHider):
                # Add selection to set
                # If the setHider is Extra will query shape, if is Normal will query transform
                removeNameSpace()

                if shapeMode == 'On':
                    addNameSpace()
                    shapesCtrl = cmds.listRelatives(sel, s=True, fullPath=True)
                    polys = cmds.filterExpand(sel, sm=34, fullPath=True)
                    cmds.sets (shapesCtrl, edit=True, forceElement=setHider)
                    cmds.sets (polys, edit=True, forceElement=setHider)
                if shapeMode == 'Off':
                    addNameSpace()
                    cmds.sets (sel, edit=True, forceElement=setHider)
                # Query all
                queryAllSet()
                # Hide set
                hideSet()
                # Turn on display invisible faces for shapes
                for shape in shapes:
                    cmds.polyOptions (shape, displayInvisibleFaces=1)
                # Deselect
                cmds.select(cl=True)
        else:
            cmds.warning(nothingSelected)
    except:
        createSettingsHider()
#-----------------------------------------------------------#
def hidePolys():
    global setHider, lastPolys, lastPoly
    queryAllSet()
    try:
        cmds.hide(polys)
    except:
        # get the last polygon for every shape in set
        lastPolys = []
        # query lastPoly for every shape
        for shape in shapes:
            desgote = cmds.filterExpand(shape[0] +'.f[*]', sm=34, fullPath=True)
            cmds.select(desgote[-1])
            sel = cmds.ls(sl=True)
            lastPolys.append(sel)
        # remove last poly for every shape
        for lastPoly in lastPolys:
            # Show lastPoly
            cmds.showHidden(lastPoly)
            for poly in polys:
                if poly == lastPoly[0]:
                    polys.remove(poly)        
        # Hide all polys except the last one for each shapemesh            
        cmds.hide(polys)
        # Hide last poly for each shapeMesh, and select each shape just for avoid bug
        for lastPoly in lastPolys:
            cmds.polyHole(lastPoly[0], assignHole = 1)
        for shape in shapes:
            cmds.select(shape)
###############
def showPolys():
    global setHider
    try:
        removeNameSpace()
        if cmds.getAttr(FCM_Hider_Settings + '.' + setHider + '_State') == 0:
            addNameSpace() 
            # show all polys in set
            try:
                cmds.showHidden(polys)
                
                # query lastPoly for every shape
                lastPolys = []
                queryAllSet()
                for shape in shapes:
                    desgote = cmds.filterExpand(shape[0] +'.f[*]', sm=34, fullPath=True)
                    cmds.select(desgote[-1])
                    sel = cmds.ls(sl=True)
                    lastPolys.append(sel)
                # remove last poly for every shape
                for lastPoly in lastPolys:
                    for poly in polys:
                        if poly == lastPoly[0]:
                            polys.remove(poly)
                # Show last poly for each shapeMesh, and select each shape just for avoid bug
                for lastPoly in lastPolys:
                    cmds.polyHole(lastPoly[0], assignHole = 0)
                
            except:
                pass
    except:
        pass
#-----------------------------------------------------------#
def hideSet():
    global setHider, namespaceHider
    if cmds.objExists(setHider):
        try:
            ############
            value = 0  #
            ############
            currentSel = cmds.ls (sl=True)
            # Query all
            queryAllSet()
            ## set visibility for transform OFF
            # Check if is Extra or Normal, for Extras it will hide only shapes

            for item in transformAndShapeSet:
                try:
                    cmds.setAttr(item + '.visibility', value)
                except:
                    cmds.setAttr(item + '.lodVisibility', value)
            # Set visibility for polys OFF
            hidePolys()
            # select current sel
            cmds.select (currentSel)
            # print
            print (setHided),
        except:
            createSettingsHider()
    else:
        cmds.warning("set doesn't exists")
    
    ######################
    # Remove namespace for this operation
    removeNameSpace()
    # Set Attr State to Off    
    cmds.setAttr( FCM_Hider_Settings + '.' + (setHider + '_State'), 0)
    # Turn off Icon
    checkStateIcon()
#-----------------------------------------------------------#
def showSet():
    global setHider, namespaceHider
    if cmds.objExists(setHider):
        ############
        value = 1  #
        ############
        currentSel = cmds.ls (sl=True)
        # Query all
        queryAllSet()
        ## set visibility for transform ON
        for item in transformAndShapeSet:
            try:
                cmds.setAttr(item + '.visibility', value)
            except:
                cmds.setAttr(item + '.lodVisibility', value)
        # Set visibility for polys ON
        showPolys()
        # select current sel
        cmds.select (currentSel)
        # print
        print (setVisible),
    else:
        cmds.warning(setDoesntExists)
    #----------------------------#
    # Remove namespace for this operation
    removeNameSpace()
    # Set Attr State to On
    cmds.setAttr( FCM_Hider_Settings + '.' + (setHider + '_State'), 1)
    # Turn off Icon
    checkStateIcon()
#-----------------------------------------------------------#
def showOrHideButton():
    global setHider
    
    # Check settings
    try:
        contentSet = cmds.sets(setHider, q=True)
        # check if it's empty
        if str(contentSet) == 'None':
            cmds.warning('Set empty')
        else:
            removeNameSpace()
            if cmds.getAttr( FCM_Hider_Settings + '.' + (setHider + '_State') ):
                addNameSpace()
                hideSet()
            else:
                addNameSpace()
                showSet()
    except:
        createSettingsHider()
        checkAllIconSets()
#-----------------------------------------------------------#
def ShowOrHideAllSetsButton():   
    global choise    
    if cmds.getAttr(FCM_Hider_Settings + '.All_Sets_Hider_State'):
        choise = 'hide'; ShowOrHideAllSets()
    else:
        choise = 'show'; ShowOrHideAllSets()
#-----------------------------------------------------------#
def checkStateIcon():
    global setHider, namespaceHider
    try:
        '''
        # # # check if All_Sets_Hider is empty # # #
        allSets = cmds.sets(All_Sets_Hider, q=True)
        result = []
        for set in allSets:
            contentSet = cmds.sets(set, q=True)
            result.append(contentSet)
            if result == [None, None, None, None, None, None, None, None, None]:
                # Set icon Empty
                cmds.iconTextButton ( (All_Sets_Hider + "button"), e=True, image=("Icons_Hider/" + 'All_Sets_Hider' + "_Empty" + ".png") )
            else:
                # All sets hider is not empty
                # Check settings
                if cmds.getAttr( (FCM_Hider_Settings + '.All_Sets_Hider_State') ):
                    # Icon On
                    cmds.iconTextButton ( (All_Sets_Hider + "button"), e=True, image=("Icons_Hider/" + All_Sets_Hider + ".png") )
                else:
                    # Icon Off
                    cmds.iconTextButton ( (All_Sets_Hider + "button"), e=True, image=("Icons_Hider/" + All_Sets_Hider + "_Off" + ".png") )
        '''
        #------------------------------------------#
        # # # Check body and extra icon # # # 
        # query set
        addNameSpace()
        contentSet = cmds.sets(setHider, q=True)
        # check if it's empty
        if str(contentSet) == 'None':
            removeNameSpace()
            cmds.iconTextButton ( (setHider + "button"), e=True, image=("Icons_Hider/" + setHider + "_Empty" + ".png") )
        else:
            removeNameSpace()
            # Check settings
            if cmds.getAttr( FCM_Hider_Settings + '.' + (setHider + '_State') ):
                # Icon On
                cmds.iconTextButton ( (setHider + "button"), e=True, image=("Icons_Hider/" + setHider + ".png") )
            else:
                # Icon Off
                cmds.iconTextButton ( (setHider + "button"), e=True, image=("Icons_Hider/" + setHider + "_Off" + ".png") )
    except:
        pass
#-----------------------------------------------------------#
def checkAllIconSets():
    global setHider
    setHider = Head_Hider; removeNameSpace(); checkStateIcon()
    setHider = Torso_Hider; removeNameSpace(); checkStateIcon()
    setHider = Arm_R_Hider; removeNameSpace(); checkStateIcon()
    setHider = Arm_L_Hider; removeNameSpace(); checkStateIcon()
    setHider = Leg_R_Hider; removeNameSpace(); checkStateIcon()
    setHider = Leg_L_Hider; removeNameSpace(); checkStateIcon()
    setHider = Extra_One_Hider; removeNameSpace(); checkStateIcon()
    setHider = Extra_Two_Hider; removeNameSpace(); checkStateIcon()
    setHider = Extra_Three_Hider; removeNameSpace(); checkStateIcon()

#-----------------------------------------------------------#
def ShowOrHideAllSets():
    global setHider
    sets_In_AllSetsHider = cmds.sets(All_Sets_Hider,q=True)
    # check if is empty
    result = []    
    for set in sets_In_AllSetsHider:
        contentSet = cmds.sets(set, q=True)
        result.append(contentSet)
    if result == [None, None, None, None, None, None, None, None, None]:
        cmds.warning('Set empty')
        # if set is not empty
    else:
        for set in sets_In_AllSetsHider:
            setHider = set
            # Hide or Show all sets depending of choise before calling function
            if choise == 'show':
                showSet()
                cmds.setAttr( FCM_Hider_Settings + '.All_Sets_Hider_State', 1)
            if choise == 'hide':
                hideSet()
                cmds.setAttr( FCM_Hider_Settings + '.All_Sets_Hider_State', 0)
        # Turn on Icon
        checkStateIcon()

#-----------------------------------------------------------#
def selectSet():
    if cmds.objExists(setHider):
        cmds.select(setHider)
    else:
        cmds.warning("set doesn't exists")
#-----------------------------------------------------------#
def showAllHiddenFaces():
    if cmds.objExists('defaultHideFaceDataSet'):
        cmds.showHidden('defaultHideFaceDataSet')
        print(allFacesAreVisible),
    else:
        cmds.warning('No faces hidded')

'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                    LOCK FUNCTIONS
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
def unlockAllVismeshes():
    # Query 
    shapesAndShapesOrig = cmds.ls (v=True, type='mesh')
    meshes = cmds.filterExpand(shapesAndShapesOrig, sm= 12 )
    groups = cmds.ls(type='transform')
    groupsAndMeshes = groups + meshes
    try:
        # For meshes
        for item in groupsAndMeshes:
            if cmds.getAttr (item + '.overrideDisplayType') == 2:
                cmds.setAttr (item + '.overrideDisplayType', 0)
    except:
        pass
    try:
        # For displayLayers
        displayLayers = cmds.ls(type='displayLayer', l=True) 
        for ld in displayLayers:
            cmds.setAttr(ld + '.displayType', 0)     
    except:
        pass
    print (allVisMeshSelectable),
#-----------------------------------------------------------#
def unlockAllVisible():
    # Query current Sel
    currentSel = cmds.ls(sl=True)
    # Querys
    transform = cmds.ls(type='transform', v=True)
    mesh = cmds.ls(type='mesh', v=True)
    annotationShapes = cmds.ls(type='annotationShape')
    visNurbsShapes = cmds.ls(type='nurbsCurve', v=True)
    visNurbsTransform = cmds.ls(cmds.pickWalk (visNurbsShapes, d='up') )
    
    # Add all to nodes
    nodes = annotationShapes + visNurbsTransform + visNurbsShapes + transform + mesh
    
    for item in nodes:
        try:
            cmds.setAttr(item + '.overrideDisplayType', 0)
            cmds.setAttr(item + '.template', 0)
        except:
            pass
    #-------------------#
    try:
        # For displayLayers
        displayLayers = cmds.ls(type='displayLayer', l=True)
        # For displayLayers
        displayLayers = cmds.ls(type='displayLayer', l=True) 
        for ld in displayLayers:
            cmds.setAttr(ld + '.displayType', 0)     
    except:
        pass
    cmds.select(currentSel)
    print ('All selectable'),
#-----------------------------------------------------------#
def lockSelection():  
    # Query 
    sel = cmds.ls(sl=True)
    if len(sel) > 0:
        selShape = cmds.ls(cmds.pickWalk (sel, d='down') )
        # Add all to nodes
        nodes = sel + selShape 
        
        for item in nodes:
            try:
                cmds.setAttr(item + '.overrideDisplayType', 1)
            except:
                pass
        
        print ('Selection Locked'),
    else:
        cmds.warning(nothingSelected)


'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                    REMOVE FUNCTIONS DEF
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
def removeAllBodySets():
    global setHider
    currentSel = cmds.ls(sl=True)
    if cmds.objExists(Head_Hider):setHider = Head_Hider;removeSet()
    if cmds.objExists(Torso_Hider):setHider = Torso_Hider;removeSet()
    if cmds.objExists(Arm_R_Hider):setHider = Arm_R_Hider;removeSet()
    if cmds.objExists(Arm_L_Hider):setHider = Arm_L_Hider;removeSet()
    if cmds.objExists(Leg_R_Hider):setHider = Leg_R_Hider;removeSet()
    if cmds.objExists(Leg_L_Hider):setHider = Leg_L_Hider;removeSet()
    cmds.select(currentSel)
    print(allBodySetsRemoved), 
#-----------------------------------------------------------#
def removeAllExtraSets():
    global setHider
    currentSel = cmds.ls(sl=True)
    if cmds.objExists(Extra_One_Hider):setHider = Extra_One_Hider;removeSet()
    if cmds.objExists(Extra_Two_Hider):setHider = Extra_Two_Hider;removeSet()
    if cmds.objExists(Extra_Three_Hider):setHider = Extra_Three_Hider;removeSet()
    cmds.select(currentSel)
    print(allExtraSetsRemoved), 
#-----------------------------------------------------------#
def removeAllHider():
    removeAllBodySets()
    removeAllExtraSets()
    if cmds.objExists(FCM_Hider_Settings):cmds.delete(FCM_Hider_Settings)
    if cmds.objExists('All_Sets_Hider'):cmds.delete('All_Sets_Hider')
    if cmds.window ("windowHider", exists=True):
        cmds.deleteUI ("windowHider")
    print(allRemoved), 
################
def confirmRemoveAllHider():
    response = cmds.confirmDialog(
                    title='Confirm Window',
                    message=removeAllConfirm, 
                    button=['Yes', 'No'],
                    defaultButton='Yes',
                    cancelButton='Cancel',
                    dismissString='Cancel')
    if response == 'Yes':
        removeAllHider()
    if response == 'No':    
        print(keepYourSecrets), 
#-----------------------------------------------------------#
def removeSet():
    global setHider
    # Show set
    showSet()
    # Query all set
    allSet = cmds.sets(setHider, q=True)
    # Remove all from set
    cmds.sets(allSet, edit=True, rm=setHider)
    checkStateIcon()
#-----------------------------------------------------------#
def removeSelection():
    global setHider
    # Query sel
    sel = cmds.ls(sl=True)
    if len(sel) > 0:
        if cmds.objExists(setHider):
            value = 1

            # Query Transform
            transformSel = cmds.ls(sl=True, type='transform')
            # Query Polys
            polysSel = cmds.filterExpand(sel, sm=34, fullPath=True)
            # Query Shape
            shapesSel = cmds.listRelatives(sel, s=True)
            # Remove shapes from set
            cmds.sets (shapesSel, edit=True, rm=setHider)
            # Remove sel from Set
            cmds.sets (sel, edit=True, rm=setHider)

            try:
                # Set shape visibility ON
                for item in shapesSel:
                    try:
                        cmds.setAttr(item + '.visibility', value)
                    except:
                        cmds.setAttr(item + '.lodVisibility', value)
            
            except:
                pass
            
            # Set transfom visibility ON
            for item in transformSel:
                try:
                    cmds.setAttr(item + '.visibility', value)
                except:
                    cmds.setAttr(item + '.lodVisibility', value)
            if value == 1:
                value = 0
            # Set polys visibility ON Method 1
            cmds.showHidden(polysSel)
            # Set polys visibility ON Method 2
            try:
                for poly in polysSel:
                    cmds.polyHole (poly, assignHole = value)
            except:
                pass
            checkStateIcon()
            print(selRemoved), 
        else:
            cmds.warning(setDontExists) 
    else:
        cmds.warning(nothingSel)

'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                    NAMESPACES DEF
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
def queryNamespace():
    # Query nameSpace
    namespaceHider = cmds.referenceQuery( '*:FCM_Hider_Settings', namespace=True, shortName=True )
    # add ":"
    namespaceHider = namespaceHider + ":"

#-----------------------------------------------------------#    
def removeNameSpace():
    global setHider, namespaceHider
    if len(namespaceHider) > 0:
        numberNS = len(namespaceHider)
        setHider = setHider[numberNS:]

#-----------------------------------------------------------#    
def addNameSpace():
    global setHider, namespaceHider
    if len(namespaceHider) > 0:
        setHider = namespaceHider+setHider
        

'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                SAVE AND LOAD SETS DEF
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''

def saveSetsHider():
    if namespaceHiderForWindow == 'Created in the scene':
        # just in case
        createAllSets()
        # Declare sets
        allSets = [Head_Hider,Torso_Hider,Arm_R_Hider,Arm_L_Hider,
        Leg_R_Hider,Leg_L_Hider, Extra_One_Hider,Extra_Two_Hider,Extra_Three_Hider]    
        # Open save file window
        SourceFile = cmds.fileDialog2(startingDirectory ="/usr/u/bozo/myFiles/", fileFilter="Python File(*.py)")
        SourceFile = ''.join([str(elem) for elem in SourceFile]) 
        # Open file (overwrite mode)
        fileHandle = open(  (SourceFile ), 'w' )
        # write remove existent set
        fileHandle.write("## Remove existent sets\n" + "removeAllBodySets()\n" + "removeAllExtraSets()\n")
        # Write create All_Sets_Hider set
        fileHandle.write( "## Create all sets\n"+ "createAllSets()\n" + "## Select each set content and create set\n")
        for set in allSets:       
            # Query content
            setContent = cmds.sets(set, q=True )
            if str(setContent) == 'None':
                pass
            else:
                # write open selection
                fileHandle.write('cmds.select(')
                # write every item in the selection
                for item in setContent:
                    fileHandle.write('"'+ item+'",')
                # write: close selection and add new line
                fileHandle.write(')'+'\n')
                # write: create set with selection
                fileHandle.write( 'cmds.sets( edit=True, fe=' + set + ')\n')
        # write create settings and run UI
        fileHandle.write("## Select clear\n" + "cmds.select(cl=True)\n")
        # write HiderUI
        fileHandle.write("## Check all icons\n" + "checkAllIconSets()")
        # close file
        fileHandle.close()
        # Print
        print(setsExportSucces), 
    else:
        cmds.confirmDialog( title='FCM Hider Warning', message=errorExportSets, button='Ok')

def LoadSetsHider():
    try:
        # Open file
        SourceFile = cmds.fileDialog(m=0)
        # Read file
        with open(SourceFile, 'r') as filehandle:
            filecontent = filehandle.read()
        # Execute file
        exec(filecontent)
        print(setsLoadSucces), 
    except:
        cmds.error(errorLoadSets)
     
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                    WINDOW FUNCTIONS DEF
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''

def inViewMessageHider():
    # For using inViewMessage using the messageHider variable
    global messageHider
    cmds.inViewMessage (amg="<span style=\"color:#82C99A;\"> "+messageHider+" </span> ", 
    dragKill=True, pos='topCenter',fade=True)
#-----------------------------------------------------------#  
def toggleEditMode():
    if cmds.window ('windowHider',q=True, h=True) == (36 + highWindow) :
        # Edit mode ON
        # change icon
        cmds.iconTextButton ('Edit_Modebutton', e=True,
        image1="Icons_Hider/Contract_Hider.png")
        # change window size
        cmds.window ('windowHider', edit=True, w=widthWindow, h=(74 + highWindow))
        # set settings
        cmds.setAttr (FCM_Hider_Settings +'.Edit_Mode_State', 1)
    else:
        # Edit mode OFF
        # change icon
        cmds.iconTextButton ('Edit_Modebutton', e=True,
        image1="Icons_Hider/Expand_Hider.png")
        # change window size
        cmds.window ('windowHider', edit=True, w=widthWindow, h=(36 + highWindow))
        # set settings
        cmds.setAttr (FCM_Hider_Settings+'.Edit_Mode_State', 0)
###############
def checkEditMode():
    if cmds.getAttr( FCM_Hider_Settings + '.Edit_Mode_State' ):
        # Edit mode ON
        # change icon
        cmds.iconTextButton ('Edit_Modebutton', e=True,
        image1="Icons_Hider/Contract_Hider.png")
    
        # change window size
        cmds.window ('windowHider', edit=True, w=widthWindow, h= (74 + highWindow) )
    else:
        # Edit mode ON
        # change icon
        cmds.iconTextButton ('Edit_Modebutton', e=True,
        image1="Icons_Hider/Expand_Hider.png")
        # change window size
        cmds.window ('windowHider', edit=True, w=widthWindow, h= (36 + highWindow))
#-----------------------------------------------------------#
def objectModeHider():
    global messageHider
    # Object mode
    cmds.selectMode(object=True)
    # selectType all active
    mel.eval('selectMode -object; selectType -handle 1 -ikHandle 1 -joint 1 -nurbsCurve 1 -cos 1 -stroke 1 -nurbsSurface 1 -polymesh 1 -subdiv 1 -plane 1 -lattice 1 -cluster 1 -sculpt 1 -nonlinear 1 -particleShape 1 -emitter 1 -field 1 -spring 1 -rigidBody 1 -fluid 1 -hairSystem 1 -follicle 1 -nCloth 1 -nRigid 1 -dynamicConstraint 1 -rigidConstraint 1 -collisionModel 1 -light 1 -camera 1 -texture 1 -ikEndEffector 1 -locator 1 -dimension 1;selectType -byName gpuCache 1;')
    mel.eval('selectMode -component; selectType -cv 1 -vertex 1 -subdivMeshPoint 1 -latticePoint 1 -particle 1 -editPoint 0 -curveParameterPoint 0 -surfaceParameterPoint 0 -puv 0 -polymeshEdge 0 -subdivMeshEdge 0 -isoparm 0 -surfaceEdge 0 -surfaceFace 1 -springComponent 0 -facet 0 -subdivMeshFace 1 -hull 0 -rotatePivot 0 -scalePivot 0 -jointPivot 0 -selectHandle 0 -localRotationAxis 0 -imagePlane 0;')
    mel.eval('changeSelectMode -object')#-----------------------------------------------------------#
    # inView Message
    messageHider = 'Object Mode'; inViewMessageHider()

def switchPolyOrNurbsSel():
    global messageHider
    if cmds.iconTextButton('toggleFacesNurbsCurve', q=True, i=True) == "Icons_Hider/Only_Faces_Hider.png":
        # # Select only nurbsCurve # #
        # object mode
        objectModeHider()
        # turn on curves CVs selection
        cmds.selectType (cv=True)
        # only curves
        mel.eval('setObjectPickMask "All" 0;setObjectPickMask "Curve" true')
        # inview message
        messageHider = 'NurbsCurve selection Mode'; inViewMessageHider()
        # change icon
        cmds.iconTextButton ('toggleFacesNurbsCurve', e=True, i="Icons_Hider/Only_NurbsCurve_Hider.png")
    else:
        # # Select only faces # #
        mel.eval('changeSelectMode -component')
        mel.eval('setComponentPickMask "Facet" true; ')
        # turn off CVs point selection
        cmds.selectType (cv=False)

        # inview message
        messageHider = 'Poly Faces selection Mode'; inViewMessageHider()
        # change icon
        cmds.iconTextButton ('toggleFacesNurbsCurve', e=True, i="Icons_Hider/Only_Faces_Hider.png")

'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                SELECT TEMPLATE LINE DEF
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''

def growSelection():
    cmds.select(cmds.listConnections (t='transform'))
def filterOnlyCurves():
    sel = cmds.ls(sl=True)
    onlyCurves = cmds.filterExpand(sel, sm=9, fullPath=True)
    cmds.select(onlyCurves)
    print( 'You have selected: ' + str(onlyCurves)),
def printSelected():
    sel = cmds.ls(sl=True)
    print( str(len(sel)) ),

def SelectTemplateLineWindow():
    if cmds.window ("Select_Template_Line", exists=True ):
        cmds.deleteUI ("Select_Template_Line")
    selectTemplateLine = cmds.window ("Select_Template_Line", title="Select Template Line", s=False)
    cmds.columnLayout(adjustableColumn=True)
    cmds.text(l='Usage: First select pole vector Ctrl\nThen grow selection, Filter and add it to a Set', h=30, fn='boldLabelFont')
    cmds.separator()
    cmds.button(l='1- Grow selection', c='growSelection()')
    cmds.separator()
    cmds.button(l='2- Filter Only Curves', c='filterOnlyCurves()')
    cmds.separator()
    cmds.button(l='3- Print number selected', c='printSelected()')
    cmds.showWindow( selectTemplateLine )
    cmds.window ('Select_Template_Line', edit=True, w=300, h=110)
    print('Select Template Line Window'),
def mirrorCtrlsHider():
    global setHiderParent, setHiderChild
    L_Content = []; finalContentL = []; L_item = []
    for item in setHiderParent:
        L_item = item.replace(R_Variable, L_Variable)
        # check if L_item is diferent than R_item
        if L_item != item:
            L_Content.append(L_item)
            for itemL in L_Content:
                try:
                    cmds.select(itemL)
                    finalContentL.append(itemL)
                    cmds.select(finalContentL)
                    sel = cmds.ls(sl=True)
                    cmds.sets(sel, fe=setHiderChild)
                    cmds.select(cl=True)            
                except:
                        pass
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                    MIRROR DEF
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''

def mirrorCtrlsHider():
    global setHiderParent, setHiderChild
    L_Content = []; finalContentL = []; L_item = []
    for item in setHiderParent:
        L_item = item.replace(R_Variable, L_Variable)
        # check if L_item is diferent than R_item
        if L_item != item:
            L_Content.append(L_item)
            for itemL in L_Content:
                try:
                    cmds.select(itemL)
                    finalContentL.append(itemL)
                    cmds.select(finalContentL)
                    sel = cmds.ls(sl=True)
                    cmds.sets(sel, fe=setHiderChild)
                    cmds.select(cl=True)            
                except:
                        pass

#------------------------------#             
def tryNomenclaturesMirror():
    global R_Variable, L_Variable
    R_Variable = "R_"; L_Variable = "L_"; mirrorCtrlsHider()
    R_Variable = "_R"; L_Variable = "_L"; mirrorCtrlsHider()
    R_Variable = "_R_"; L_Variable = "_L_"; mirrorCtrlsHider()
    R_Variable = "r_"; L_Variable = "r_"; mirrorCtrlsHider()
    R_Variable = "_r"; L_Variable = "_l"; mirrorCtrlsHider()
    R_Variable = "_r_"; L_Variable = "_l_"; mirrorCtrlsHider()
    R_Variable = "Right"; L_Variable = "Left"; mirrorCtrlsHider()
    R_Variable = "right"; L_Variable = "left"; mirrorCtrlsHider()
    R_Variable = "rt"; L_Variable = "lf"; mirrorCtrlsHider()
    R_Variable = "Rt"; L_Variable = "Lf"; mirrorCtrlsHider()
    R_Variable = "RGT"; L_Variable = "LFT"; mirrorCtrlsHider()
    R_Variable = "Rgt"; L_Variable = "Lft"; mirrorCtrlsHider()
#------------------------------#             
def mirrorPolyHider():
    cmds.select(setHiderParent)
    mel.eval('reflectionSetMode objectx')
    mel.eval('reflectionSetMode none')
    cmds.select(setHiderParent, tgl=True)
    # Add selection to child set
    cmds.sets(fe=setHiderChild)
    # Select clear
    cmds.select(cl=True)
#------------------------------#
# Aca tendria que usar la funcion que me quedo en temp 3 para seleccionar objetos sueltos
#------------------------------#
def mirrorHider():
    global setHider, setHiderParent, setHiderChild
    '''
    # change icons for loading
    cmds.iconTextButton ("Arm_L_Hiderbutton", e=True, i="Icons_Hider/Loading_Hider.png")
    cmds.iconTextButton ("Leg_L_Hiderbutton", e=True, i="Icons_Hider/Loading_Hider.png")
    # missing refresh icon
    '''
    try:
        # Apply mirror from Arm_R_Hider to Arm_L_Hider
        setHiderParent = cmds.sets(Arm_R_Hider, q=True)
        setHiderChild = Arm_L_Hider
        tryNomenclaturesMirror()
        mirrorPolyHider()
        setHider = Arm_L_Hider
        checkStateIcon()
        print ('Mirror succesuful'),
    except:
        setHider = Arm_L_Hider
        checkStateIcon()

    try:
        # apply mirror from Leg_R_Hider to Leg_L_Hider
        setHiderParent = cmds.sets(Leg_R_Hider, q=True)
        setHiderChild = Leg_L_Hider
        tryNomenclaturesMirror()
        mirrorPolyHider()
        setHider = Leg_L_Hider
        checkStateIcon()
        print ('Mirror succesuful'),
    except:
        setHider = Leg_L_Hider
        checkStateIcon()

'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                    CHECK ALL SETS DEF
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
def waitAndRefresh():
    cmds.refresh(cv=True)
    time.sleep(0.3)
    cmds.refresh(cv=True)

def cycleTurnOnAndOff():
    waitAndRefresh()
    hideSet()
    waitAndRefresh()
    addNameSpace()
    showSet()
    waitAndRefresh()
    addNameSpace()
    hideSet()
    waitAndRefresh()
    addNameSpace()
    showSet()
def checkAllSets():
    global setHider, choise
    
    response = cmds.confirmDialog(
                    title='Confirm Check all sets',
                    message=confirmCheckAllSets,
                    button=['Yes', 'No'],
                    defaultButton='Yes',
                    cancelButton='Cancel',
                    dismissString='Cancel')
    if response == 'Yes':
        # show all sets
        choise = 'show'; ShowOrHideAllSets()
        # create All sets list with a specific order
        allSetsCheck = [Head_Hider,Torso_Hider,Arm_R_Hider,Arm_L_Hider,
        Leg_R_Hider,Leg_L_Hider, Extra_One_Hider,Extra_Two_Hider,Extra_Three_Hider]    
        # create progress window
        cmds.progressWindow( title='Progress Hider test', isInterruptable=True )                                 
        amount = 0
        for set in allSetsCheck:
            cmds.progressWindow( edit=True, progress=amount, status= ('Testing: ' + set  ) )
            setHider = set
            cycleTurnOnAndOff()
            amount = amount+11
            # Check if the dialog has been cancelled
            if cmds.progressWindow( query=True, isCancelled=True ) :
                break
            # Check if end condition has been reached
            if cmds.progressWindow( query=True, progress=True ) >= 100 :
                break    
        cmds.progressWindow(endProgress=1)
#-----------------------------------------------------------#############
def cycleTurnOnAndOffIsolate():
    waitAndRefresh()
    hideSet()
    waitAndRefresh()
    addNameSpace()
    showSet()
    waitAndRefresh()
    addNameSpace()
    hideSet()
    waitAndRefresh()
    addNameSpace()
    showSet()
    waitAndRefresh()
    addNameSpace()
    hideSet()
def checkAllSetsIsolate():
    global setHider, choise
    # Center view
    # show all sets
    choise = 'hide'; ShowOrHideAllSets()
    # create All sets list with a specific order
    allSetsCheck = [Head_Hider,Torso_Hider,Arm_R_Hider,Arm_L_Hider,
    Leg_R_Hider,Leg_L_Hider, Extra_One_Hider,Extra_Two_Hider,Extra_Three_Hider]
    # create progress window
    cmds.progressWindow( title='Progress Hider test', isInterruptable=True )                                 
    amount = 0
    for set in allSetsCheck:
        cmds.progressWindow( edit=True, progress=amount, status= ('Testing: ' + set  ) )
        setHider = set
        cycleTurnOnAndOffIsolate()
        amount = amount+11
        # Check if the dialog has been cancelled
        if cmds.progressWindow( query=True, isCancelled=True ) :
            break
        # Check if end condition has been reached
        if cmds.progressWindow( query=True, progress=True ) >= 100 :
            break    
    cmds.progressWindow(endProgress=1)
    choise = 'show'; ShowOrHideAllSets()
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                    HELP AND CONTACT WINDOW DEF
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''

def launchtutorial():
    cmds.launch (web="https://youtu.be/RDHIFQfD12g")

def toggleImageHelpWindow():
    if cmds.image("helpwindowimage", q=True, image=True) == "Icons_Hider/Help_2_On_Hider.png":
        cmds.image ("helpwindowimage", e=True, image="Icons_Hider/Help_2_Off_Hider.png")
    else:
        cmds.image ("helpwindowimage", e=True, image="Icons_Hider/Help_2_On_Hider.png")
    
def helpWindow():
    
    if cmds.window ('HelpWindowHider', exists=True):
        cmds.deleteUI ("HelpWindowHider")
    # Window template
    helpWindowHider = cmds.window('HelpWindowHider',  s=False, h=680, w=656, title="Help Window Hider")
    scrollLayout = cmds.scrollLayout(horizontalScrollBarThickness=20, verticalScrollBarThickness=16)

    cmds.image(i="Icons_Hider/Help_1_Hider.png")
    form = cmds.formLayout()
    # button toggle image
    object = cmds.button (l="", w=200, h=28, c="toggleImageHelpWindow()", backgroundColor=[0.72,0.15,0.16])
    cmds.formLayout (form, edit=True, attachForm= [[object, "top", 5], [object, "left", 215]])
    # text toggle image
    object = cmds.text(l='Press here repeatedly to see ', font='boldLabelFont')
    cmds.formLayout (form, edit=True, attachForm= [[object, "top", 12], [object, "left", 240]])

    cmds.setParent('..')

    cmds.image('helpwindowimage',i="Icons_Hider/Help_2_On_Hider.png")
    
    # Creating elements with custom position
    form = cmds.formLayout()
    
    object = cmds.text (l="By Francisco Cerchiara Montero", font='boldLabelFont')
    cmds.formLayout (form, edit=True, attachForm= [[object, "top", 5], [object, "left", 470]])
    
    object = cmds.button (l="Link to online tutorial", c="launchtutorial()", backgroundColor=[0.72,0.15,0.16])
    cmds.formLayout (form, edit=True, attachForm= [[object, "top", 0], [object, "left", 10]])
    
    cmds.setParent('..')
    cmds.showWindow (helpWindowHider)

def contactWindow():
    # Contact Window
    if cmds.window ("FCM_Contact", exists=True ):
        cmds.deleteUI ("FCM_Contact")
    FCMContact = cmds.window ("FCM_Contact", title="Contact", s=False)
    
    
    cmds.rowColumnLayout( numberOfColumns=2, columnAttach=(1, 'right', 0), columnWidth=[(1, 100), (2, 250)] )
    cmds.text( label='Name:  ' )
    name = cmds.textField(text='Francisco Cerchiara Montero', editable=True)
    cmds.text( label='Email:  ' )
    address = cmds.textField(text='FranCM127@hotmail.com', editable=True)
    cmds.text( label='Facebook:  ' )
    phoneNumber = cmds.textField(text='www.facebook.com/Fran127', editable=True)
    cmds.text( label='Linked-In:  ' )
    email = cmds.textField(text='www.linkedin.com/in/francm3danimator/', editable=True)
    
    #    Attach commands to pass focus to the next field if the Enter
    #    key is pressed. Hitting just the Return key will keep focus
    #    in the current field.
    #
    cmds.textField( name, edit=True, enterCommand=('cmds.setFocus(\"' + address + '\")') )
    cmds.textField( address, edit=True, enterCommand=('cmds.setFocus(\"' + phoneNumber + '\")') )
    cmds.textField( phoneNumber, edit=True, enterCommand=('cmds.setFocus(\"' + email + '\")') )
    cmds.textField( email, edit=True, enterCommand=('cmds.setFocus(\"' + name + '\")') )
    
    cmds.showWindow( FCMContact )

'''''''''''''''''''''''''''''''''''''''''''''''''''''''''
                    WINDOW HIDER DEF
            
'''''''''''''''''''''''''''''''''''''''''''''''''''''''''

# Window Size
highWindow = 20
widthWindow = 388


## For all buttons sets
def buttonWindowHider():
    global shapeMode
    removeNameSpace()
    cmds.iconTextButton ( (setHider + "button"), style="iconOnly",
    ann=blueButtons_Ann, commandRepeatable=True, i=("Icons_Hider/" + setHider + ".png"),
    c=commandButton ) 
    cmds.popupMenu(postMenuCommand = popUpButton)
    cmds.menuItem (i="Icons_Hider/PopUp_Add_Hider.png", l="Add Selection", c= "shapeMode = 'Off'; addSelectionToSet()")
    cmds.menuItem (i="Icons_Hider/PopUp_Add_Hider.png", l="Add Selection Shape", c= "shapeMode = 'On'; addSelectionToSet()")
    cmds.menuItem (divider=True)
    cmds.menuItem (i="Icons_Hider/PopUp_Remove_Hider.png", l="Remove Selection", c= "removeSelection()")
    cmds.menuItem (i="Icons_Hider/PopUp_SelectSet_Hider.png", l="Select Set", c= "selectSet()")
    cmds.menuItem (i="Icons_Hider/PopUp_RemoveSet_Hider.png", l="Remove Set", c= "removeSet()")

def HiderUI():    
    global blueButtons_Ann, commandButton, popUpButton, setHider
    
    
    declaringNameSpaces()
    createSettingsHider()

    
    if cmds.window ('windowHider', exists=True):
        cmds.deleteUI ("windowHider")
    windowHider = cmds.window ("windowHider", s=False, title= ("FCM_Hider: " + namespaceHiderForWindow), menuBar=True)
    
    ## ### ### ### ### #### Menu bar #### ### ### ### ### ###
    # File
    cmds.menu('FileMenu', label='File')
    cmds.menuItem(l="Save Sets", c="saveSetsHider()")
    cmds.menuItem(l="Load Sets", c="LoadSetsHider()")    
    # Help
    cmds.menu('HelpMenu', label='Help' )
    cmds.menuItem( l='Video Tutorial', c="launchtutorial()")
    cmds.menuItem( l='Contact', c="contactWindow()")
    cmds.menuItem( l='About version', c="print(versionHider),")

    ## ### ### ### ### #### Column 1 #### ### ### ### ### ###

    cmds.rowColumnLayout (numberOfColumns = 11)
    # Edit Mode
    cmds.iconTextButton ('Edit_Modebutton', i="Icons_Hider/Contract_Hider.png", c="toggleEditMode()", ann=editMode_Ann)
    ## All sets
    setHider = All_Sets_Hider
    removeNameSpace()
    cmds.iconTextButton ( (setHider + "button"),
    ann=allSets_Ann, commandRepeatable=True, i=("Icons_Hider/" + setHider + ".png"),
    c="cmds.warning('Show or Hide all WIP')") 
    cmds.popupMenu(postMenuCommand = "setHider = All_Sets_Hider")
    cmds.menuItem (i="Icons_Hider/PopUp_RemoveSet_Hider.png", l="Empty Sets Body", c="removeAllBodySets()")
    cmds.menuItem (i="Icons_Hider/PopUp_RemoveSet_Hider.png", l="Empty Sets Extras", c="removeAllExtraSets()")
    cmds.menuItem (i="Icons_Hider/PopUp_SelectSet_Hider.png", l="Select All Sets", c="cmds.select(All_Sets_Hider)")
    #-----------------------------------------------------------#
    setHider = Head_Hider
    commandButton = "setHider = Head_Hider; showOrHideButton()"
    popUpButton = "setHider = Head_Hider"
    buttonWindowHider()
    
    setHider = Torso_Hider
    commandButton = "setHider = Torso_Hider; showOrHideButton()"
    popUpButton = "setHider = Torso_Hider"
    buttonWindowHider()
    
    setHider = Arm_R_Hider
    commandButton = "setHider = Arm_R_Hider; showOrHideButton()"
    popUpButton = "setHider = Arm_R_Hider"
    buttonWindowHider()
    
    setHider = Arm_L_Hider
    commandButton = "setHider = Arm_L_Hider; showOrHideButton()"
    popUpButton = "setHider = Arm_L_Hider"
    buttonWindowHider()
    
    setHider = Leg_R_Hider
    commandButton = "setHider = Leg_R_Hider; showOrHideButton()"
    popUpButton = "setHider = Leg_R_Hider"
    buttonWindowHider()
    
    setHider = Leg_L_Hider
    commandButton = "setHider = Leg_L_Hider; showOrHideButton()"
    popUpButton = "setHider = Leg_L_Hider"
    buttonWindowHider()
    
    setHider = Extra_One_Hider
    commandButton = "setHider = Extra_One_Hider; showOrHideButton()"
    popUpButton = "setHider = Extra_One_Hider"
    buttonWindowHider()
       
    setHider = Extra_Two_Hider
    commandButton = "setHider = Extra_Two_Hider; showOrHideButton()"
    popUpButton = "setHider = Extra_Two_Hider"
    buttonWindowHider()
    
    setHider = Extra_Three_Hider
    commandButton = "setHider = Extra_Three_Hider; showOrHideButton()"
    popUpButton = "setHider = Extra_Three_Hider"
    buttonWindowHider()
    
    ## ### ### ### ### #### Column 2 #### ### ### ### ### ###
    # Unlock Vis meshes 
    cmds.iconTextButton (i="Icons_Hider/Unlock_Hider.png", c='cmds.warning(rightClickToSeeButtons_Ann),', ann=rightClickToSeeButtons_Ann)
    cmds.popupMenu()
    cmds.menuItem(i="Icons_Hider/Unlock_Hider.png", l="Unlock All Visible", c= "unlockAllVisible()", ann=unlockAllVis_Ann)
    cmds.menuItem(i="Icons_Hider/Unlock_Hider.png", l="Unlock All Visible Meshes", c= "unlockAllVismeshes()", ann=unlockAllVisMeshes_Ann)
    cmds.menuItem(i="Icons_Hider/Lock_Hider.png", l="Lock Selection", c= "lockSelection()", ann=lockSelection_Ann)

    # Object mode Select
    cmds.iconTextButton (i="Icons_Hider/ObjectMode_Hider.png", c="objectModeHider()", ann=objectMode_Ann)
    # Toggle Ctrls and poly select
    cmds.iconTextButton ('toggleFacesNurbsCurve', i="Icons_Hider/Only_Faces_Hider.png", c="switchPolyOrNurbsSel()",ann=switchPolyOrNurbsCurves_Ann)
    cmds.popupMenu()
    cmds.menuItem(i="Icons_Hider/PolyColorSel_Red_Hider.png",l="Poly color selection Red", c= "cmds.displayColor ('polyFace', 13, active= True)")
    cmds.menuItem(i="Icons_Hider/PolyColorSel_Green_Hider.png", l="Poly color selection Green", c="cmds.displayColor ('polyFace', 14, active= True)")
    cmds.menuItem(i="Icons_Hider/PolyColorSel_Default_Hider.png", l="Poly color selection default", c="cmds.displayColor ('polyFace', 21, active= True)")
    # Grow selection
    cmds.iconTextButton (i="Icons_Hider/Grow_Hider.png", c="cmds.polySelectConstraint (pp=1)", commandRepeatable=True, ann=grow_Ann)
    # Shrink selection
    cmds.iconTextButton (i="Icons_Hider/Shrink_Hider.png", c="cmds.polySelectConstraint (pp=2)", commandRepeatable=True, ann=shrink_Ann)
    # Template Line Window
    cmds.iconTextButton (i="Icons_Hider/Template_Line_Hider.png", c="SelectTemplateLineWindow()", ann=templateLine_Ann)
    # Mirror 
    cmds.iconTextButton (i="Icons_Hider/Mirror_Hider.png", c="mirrorHider()", ann=mirrorButtons_Ann)
    # Check all sets
    cmds.iconTextButton (i="Icons_Hider/Show_All_Hidden_Faces_Hider.png", c="checkAllSets()", ann=checkAllSets_Ann)
    cmds.popupMenu()
    cmds.menuItem(l="Isolate mode", c="checkAllSetsIsolate()", ann= ( checkAllSets_Ann + ' but isolating every set') )
    # Extra functions
    cmds.iconTextButton (i="Icons_Hider/Extra_Functions_Hider.png",  c='cmds.warning(rightClickToSeeButtons_Ann),', ann=rightClickToSeeButtons_Ann)
    cmds.popupMenu('extraFunctions')
    cmds.menuItem(l="Show all hidden faces in the scene", c="showAllHiddenFaces()")
    # Remove All Hider
    cmds.iconTextButton (i="Icons_Hider/Remove_All_Hider.png", c="confirmRemoveAllHider()",ann=deleteAll_Ann)

    cmds.setParent('..')
    # Show window
    cmds.showWindow( windowHider )    
    # # # Check Functions # # #
    checkEditMode()
    checkAllIconSets()
