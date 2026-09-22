"""SpeedCut 2.24 - boolean / cut tool set by Joe Wu (http://im3djoe.com).

THIRD-PARTY. Not written here. The author ships it as "copy and paste script into a
python tab in maya script editor", which is exactly where it was living - Maya 2027's
scriptEditorTemp/commandExecuter-8, 7,981 lines. Saved to a file so the shelf can launch
it without the source sitting in a Script Editor tab.

Unmodified apart from removing the trailing jwSpeedCutUI() call, so importing this
module does not immediately open the window.

Its UI is wired with 85 string-valued callbacks (mc.button(c='togglevisLeft()')), which
Maya evaluates in the __main__ namespace - NOT in this module's namespace. So the
launcher publishes the module's names into __main__ before opening the UI. See show().
"""


def show():
    """Publish this module's names into __main__, then open the SpeedCut UI.

    Maya resolves string-valued UI callbacks against __main__, so without this every
    button in the window raises NameError. Functions keep this module's __globals__,
    so the ~149 module-level globals the tool relies on stay coherent.
    """
    import __main__
    namespace = globals()
    for key, value in namespace.items():
        if not key.startswith("_"):
            setattr(__main__, key, value)
    namespace["jwSpeedCutUI"]()


##--------------------------------------------------------------------------
## ScriptName : SpeedCut
## Contents   : tool set for speed up maya boolean opeeration
## Author     : Joe Wu
## URL        : http://im3djoe.com
## Since      : 2019/08
## LastUpdate : 2025/09
##            : 2.0  upgrade 2d,3d draw cut
##            : 2.1  fixing menu floating random place
##            : 2.11 adding cut corner
##            : 2.13 fixing UI bugs using workspaceControl replace window command
##            : 2.16 fixing floating window UI size bug
##            : 2.18 added finalize all
##            : 2.19 fixing UI bug
##            : 2.2  public test
##            : 2.21 fix bug nurbs convert to polygon setting missing
##            : 2.23 fix all finalize bug, added scene size
##            : 2.24 bug fix and remove numpy and itertools
## Other Note : test in maya 2023.3 windows enviroment
##              numpy dependency removed - using pure Maya API + stdlib
## Install    : copy and paste script into a python tab in maya script editor
##--------------------------------------------------------------------------

import maya.api.OpenMaya as om2
import maya.OpenMaya as om
import maya.OpenMayaUI as omui
import maya.cmds as mc
import math
import maya.mel as mel
import re
from collections import OrderedDict
import random
import operator
mel.eval('source "dagMenuProc"')

# =============================================================================
# Constants (Fix 9: replace magic numbers with named values)
# =============================================================================
BUTTON_ACTIVE_THRESHOLD = 0.285     # bgc threshold for toggle button "on" state
BUTTON_ACTIVE_THRESHOLD_ALT = 0.30  # alternate threshold used in some checks
BUTTON_ACTIVE_THRESHOLD_LOW = 0.27  # threshold for radial mirror buttons
NO_BASE_MESH = 'No Base Mesh'
MAX_BOOL_CONNECTIONS = 100          # max connections scanned in multi-index search
MERGE_VERTEX_TOLERANCE = 0.01      # polyMergeVertex distance threshold
SNAP_SEARCH_INIT_DIST = 10000000   # initial large distance for closest-point search
TINY_OFFSET_DIVISOR = 100000       # divisor for micro-offset after corner tool

# =============================================================================
# Helper Functions (Fix 4: reduce duplication, Fix 5: UI state helpers)
# =============================================================================
def _is_button_active(button_name, channel=0):
    """Check if a toggle button is active based on its background color.
    channel: 0=R, 1=G, 2=B - which color channel to test."""
    bgc = mc.button(button_name, q=True, bgc=True)
    return bgc[channel] > BUTTON_ACTIVE_THRESHOLD

def _is_button_active_alt(button_name, channel=0, threshold=BUTTON_ACTIVE_THRESHOLD_ALT):
    """Check button active state with alternate threshold."""
    bgc = mc.button(button_name, q=True, bgc=True)
    return bgc[channel] > threshold

def _get_base_mesh():
    """Get current base mesh name, or None if not set.
    Replaces repetitive 'beseMesh != No Base Mesh' guard pattern."""
    try:
        beseMesh = mc.optionMenu('baseMeshMenu', query=True, v=True)
        if beseMesh and beseMesh != NO_BASE_MESH:
            return beseMesh
    except Exception:
        pass
    return None

def _distance_3d(p1, p2):
    """Calculate 3D Euclidean distance between two points (lists/tuples)."""
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2)

def _bbox_diagonal(bbox):
    """Calculate averaged diagonal length of a bounding box [xmin,ymin,zmin,xmax,ymax,zmax]."""
    return math.sqrt(((bbox[0]-bbox[3])**2 + (bbox[1]-bbox[4])**2 + (bbox[2]-bbox[5])**2) / 3)

def _bbox_axis_length(bbox, axis):
    """Get bounding box length along a single axis ('X','Y','Z')."""
    idx = {'X': 0, 'Y': 1, 'Z': 2}[axis]
    return abs(bbox[idx+3] - bbox[idx])

def _safe_select(items, warning_msg="Nothing to select"):
    """Safely select items, showing warning if selection fails."""
    try:
        if items:
            mc.select(items)
            return True
    except Exception as e:
        mc.warning("{}: {}".format(warning_msg, str(e)))
    return False

def _eigen_symmetric_3x3(A):
    """Eigendecomposition of a 3x3 symmetric matrix using Jacobi iteration.
    Returns (eigenvalues[3], eigenvectors[3][3]) where eigenvectors[row][col].
    Replaces numpy.linalg.eigh for this specific use case."""
    # Work on a copy
    a = [row[:] for row in A]
    # Eigenvector matrix starts as identity
    v = [[1,0,0],[0,1,0],[0,0,1]]
    for _ in range(50):  # max iterations
        # Find largest off-diagonal element
        max_val = 0.0; p = 0; q = 1
        for i in range(3):
            for j in range(i+1, 3):
                if abs(a[i][j]) > max_val:
                    max_val = abs(a[i][j]); p = i; q = j
        if max_val < 1e-12:
            break
        # Compute rotation angle
        if abs(a[p][p] - a[q][q]) < 1e-15:
            theta = math.pi / 4.0
        else:
            theta = 0.5 * math.atan2(2.0 * a[p][q], a[p][p] - a[q][q])
        c = math.cos(theta); s = math.sin(theta)
        # Apply Jacobi rotation
        new_a = [row[:] for row in a]
        new_a[p][p] = c*c*a[p][p] + 2*s*c*a[p][q] + s*s*a[q][q]
        new_a[q][q] = s*s*a[p][p] - 2*s*c*a[p][q] + c*c*a[q][q]
        new_a[p][q] = 0.0; new_a[q][p] = 0.0
        for r in range(3):
            if r != p and r != q:
                new_a[r][p] = c*a[r][p] + s*a[r][q]; new_a[p][r] = new_a[r][p]
                new_a[r][q] = -s*a[r][p] + c*a[r][q]; new_a[q][r] = new_a[r][q]
        a = new_a
        # Update eigenvectors
        new_v = [row[:] for row in v]
        for r in range(3):
            new_v[r][p] = c*v[r][p] + s*v[r][q]
            new_v[r][q] = -s*v[r][p] + c*v[r][q]
        v = new_v
    eigenvalues = [a[i][i] for i in range(3)]
    return eigenvalues, v



def goCornerTool():
    mc.nurbsToPolygonsPref(polyType=1,format=2,uType=3,uNumber=1,vType=3,vNumber=1)
    hideAllCutter()
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        mc.setAttr((beseMesh +'_BoolResult.displayType'),0)
        cmd = 'doMenuComponentSelectionExt("{}", "edge", 1);'.format(beseMesh + '_bool')
        mel.eval(cmd)
        mc.scriptJob(runOnce=True, event=["SelectionChanged", runCornerTool])

def get_max_slide_distance(face_id, slide_vec, mfn_mesh, edge_mid):
    verts = mfn_mesh.getPolygonVertices(face_id)
    max_dist = 0.0
    for v in verts:
        pos = om2.MVector(mfn_mesh.getPoint(v, om2.MSpace.kWorld))
        offset_vec = pos - edge_mid
        proj = offset_vec * slide_vec   # dot product
        max_dist = max(max_dist, abs(proj))
    return max_dist

def runCornerTool():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        cleanList = ('edgeCurve_main*','edgeCurve_face*')
        for c in cleanList:
            if mc.objExists(c):
                mc.delete(c)
        sel = mc.filterExpand(expand=True, sm=32)
        if sel is None or len(sel) == 0:
            mc.warning("SpeedCut: Please select exactly one edge.")
            return
        if len(sel) == 1:
            length = edgeLength(sel[0])
            mesh_name = sel[0].split('.')[0]
            bevelXMesh = mesh_name
            bboxObj = mc.xform(bevelXMesh , q = True, ws =True, bb=True)
            lengthObj = _bbox_diagonal(bboxObj)
            edge_index = int(sel[0].split('[')[-1][:-1])
            selList = om2.MSelectionList()
            selList.add(mesh_name)
            dagPath = selList.getDagPath(0)
            mfn_mesh = om2.MFnMesh(dagPath)
            edge_iter = om2.MItMeshEdge(dagPath)
            edge_iter.setIndex(edge_index)
            p0 = edge_iter.point(0, om2.MSpace.kWorld)
            p1 = edge_iter.point(1, om2.MSpace.kWorld)
            edge_dir = om2.MVector(p1 - p0).normal()
            edge_mid = (om2.MVector(p0) + om2.MVector(p1)) * 0.5
            connected_faces = edge_iter.getConnectedFaces()
            face1, face2 = connected_faces
            normal1 = om2.MVector(mfn_mesh.getPolygonNormal(face1, om2.MSpace.kWorld)).normal()
            normal2 = om2.MVector(mfn_mesh.getPolygonNormal(face2, om2.MSpace.kWorld)).normal()
            slide_vec1 = (normal1 ^ edge_dir).normal()
            slide_vec2 = (normal2 ^ edge_dir).normal()
            distance1 = get_max_slide_distance(face1, slide_vec1, mfn_mesh, edge_mid)
            distance2 = get_max_slide_distance(face2, slide_vec2, mfn_mesh, edge_mid)
            longerDis = distance1
            if distance2 > distance1:
                longerDis = distance2 * 1
            longerDis = longerDis * 1.05
            base_curve = mc.polyToCurve(form=2, degree=1)[0]
            base_curve = mc.rename(base_curve, "edgeCurve_main")
            mc.CenterPivot()
            #check base mesh bbox
            vFactor = lengthObj/length*1.5
            mc.setAttr('edgeCurve_main.scale', vFactor, vFactor, vFactor)
            curve1 = mc.duplicate(base_curve, name="edgeCurve_face1")[0]
            mc.move(slide_vec1.x * longerDis, slide_vec1.y * longerDis, slide_vec1.z * longerDis, curve1, r=True, ws=True)
            curve2 = mc.duplicate(base_curve, name="edgeCurve_face2")[0]
            neg_vec2 = slide_vec2 * -longerDis
            mc.move(neg_vec2.x, neg_vec2.y, neg_vec2.z, curve2, r=True, ws=True)
            loft_result = mc.loft(curve2, base_curve, curve1,ch=True, u=True, c=False, ar=True, d=1, ss=1,rn=False, po=1, rsn=True)
            faces = mc.ls(mc.polyListComponentConversion(sel, tf=True), fl=True)
            selList = om2.MSelectionList()
            selList.add(faces[0].split('.')[0])  # mesh name
            dagPath = selList.getDagPath(0)
            mfn_mesh = om2.MFnMesh(dagPath)
                
            normals = []
            for f in faces:
                idx = int(f.split('[')[-1].split(']')[0])
                n = mfn_mesh.getPolygonNormal(idx, om2.MSpace.kWorld)
                normals.append([n.x, n.y, n.z])
            avg = om2.MVector(
                sum(n[0] for n in normals)/len(normals),
                sum(n[1] for n in normals)/len(normals),
                sum(n[2] for n in normals)/len(normals)
            ).normal()
            lofted_mesh = loft_result[0]
            selList2 = om2.MSelectionList(); selList2.add(lofted_mesh)
            dagPath2 = selList2.getDagPath(0)
            mfn_loft = om2.MFnMesh(dagPath2)
            lofted_normal = om2.MVector(mfn_loft.getPolygonNormal(0, om2.MSpace.kWorld)).normal()
            if (avg * lofted_normal) < 0.0:
                mc.polyNormal(lofted_mesh, normalMode=0, userNormalMode=0, ch=1)
            
            mc.select(lofted_mesh + ".f[0:1]", r=True)
            mc.polyExtrudeFacet(constructionHistory=True,keepFacesTogether=True,divisions=1,twist=0,taper=1,off=0,thickness=longerDis,smoothingAngle=30)
            newFace = mc.ls(sl=1, fl=1)
            mc.select(newFace)
            mc.delete(lofted_mesh, ch=1)
            cmd = f'doMenuComponentSelectionExt("{lofted_mesh}", "facet", 0);'
            mel.eval(cmd)
            mc.GrowPolygonSelectionRegion()
            mc.InvertSelection()
            mc.ConvertSelectionToContainedEdges()
            midEdge = mc.ls(sl=1,fl=1)
            mc.select(lofted_mesh)
            useOwnCutterShape()
            selNewCuttter = mc.ls(sl=1,fl=1)
            mc.setAttr(selNewCuttter[0] + '.cutterType', 'corner', type="string")
            for c in cleanList:
                if mc.objExists(c):
                    mc.delete(c)
            newEdge = selNewCuttter[0]+ '.' + midEdge[0].split('.')[-1]
            mc.select(newEdge)
            cmd = 'doMenuComponentSelectionExt("{}", "edge", 1);'.format(selNewCuttter[0])
            mel.eval(cmd)
            QBoxBevel()
                
            obj = selNewCuttter[0]
            sl = om2.MSelectionList(); sl.add(obj)
            dag = sl.getDagPath(0); mesh = om2.MFnMesh(dag)
            pts = mesh.getPoints(om2.MSpace.kWorld)
            # --- Oriented Bounding Box (pure Maya API, no numpy) ---
            # Build point list and compute centroid
            P = [[p.x, p.y, p.z] for p in pts]
            n = len(P)
            mean = [sum(P[i][j] for i in range(n)) / n for j in range(3)]
            # Center the points
            Pc = [[P[i][j] - mean[j] for j in range(3)] for i in range(n)]
            # 3x3 covariance matrix
            cov = [[0.0]*3 for _ in range(3)]
            for i in range(3):
                for j in range(3):
                    cov[i][j] = sum(Pc[k][i] * Pc[k][j] for k in range(n)) / max(n - 1, 1)
            # Eigendecomposition of 3x3 symmetric matrix (Jacobi iteration)
            evals, evecs = _eigen_symmetric_3x3(cov)
            # Sort eigenvectors by eigenvalue (ascending)
            order = sorted(range(3), key=lambda i: evals[i])
            evecs = [[evecs[r][order[c]] for c in range(3)] for r in range(3)]
            # Try all axis permutations and sign flips to find tightest OBB
            def _eval_obb_frame(R, Pc, mean):
                # Project centered points into frame R (3x3 row-major)
                mn = [float('inf')]*3; mx = [float('-inf')]*3
                for pt in Pc:
                    for j in range(3):
                        v = R[j][0]*pt[0] + R[j][1]*pt[1] + R[j][2]*pt[2]
                        if v < mn[j]: mn[j] = v
                        if v > mx[j]: mx[j] = v
                size = [mx[j] - mn[j] for j in range(3)]
                vol = size[0] * size[1] * size[2]
                cen_local = [(mn[j] + mx[j]) * 0.5 for j in range(3)]
                # Inverse of orthonormal R is its transpose
                cen_world = [0.0]*3
                for j in range(3):
                    for k in range(3):
                        cen_world[j] += R[k][j] * cen_local[k]
                    cen_world[j] += mean[j]
                return vol, size, cen_world
            def _det3(m):
                return (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])
                      - m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
                      + m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))
            best_vol = float('inf'); best_size = None; best_cen = None; best_R = None
            perms = [(0,1,2),(0,2,1),(1,0,2),(1,2,0),(2,0,1),(2,1,0)]
            sign_combos = [(a,b,c) for a in (1,-1) for b in (1,-1) for c in (1,-1)]
            for perm in perms:
                for signs in sign_combos:
                    # Build rotation: columns are permuted/signed eigenvectors
                    R_cols = [[evecs[r][perm[i]] * signs[i] for r in range(3)] for i in range(3)]
                    R = [[R_cols[c][r] for c in range(3)] for r in range(3)]
                    if _det3(R) < 0:
                        continue
                    # R is row-major: R[row][col]
                    vol, size, cen = _eval_obb_frame(R, Pc, mean)
                    if vol < best_vol:
                        best_vol = vol; best_size = size; best_cen = cen
                        best_R = [row[:] for row in R]
            bbox = mc.polyCube(name=f"{obj}_bbox")[0]
            mc.xform(bbox, t=best_cen, s=best_size)
            m_mat = om2.MMatrix([[best_R[0][0],best_R[0][1],best_R[0][2],0],
                                 [best_R[1][0],best_R[1][1],best_R[1][2],0],
                                 [best_R[2][0],best_R[2][1],best_R[2][2],0],
                                 [0,0,0,1]])
            rotb = om2.MTransformationMatrix(m_mat).rotation()
            mc.xform(bbox, ro=[math.degrees(rotb.x), math.degrees(rotb.y), math.degrees(rotb.z)])
            mc.parent(obj,bbox); mc.makeIdentity(obj,apply=True,t=1,r=1,s=1,n=0)
            mc.parent(obj,w=1); mc.CenterPivot(obj)
            mc.makeIdentity(obj,apply=True,t=0,r=0,s=1,n=0); mc.delete(bbox)
            mc.select(obj)
            mc.parent(obj, beseMesh + '_cutterGrp')
            mc.move(longerDis/TINY_OFFSET_DIVISOR, 0, 0, obj, relative=True, objectSpace=True)
        mc.setAttr((beseMesh +'_BoolResult.displayType'),2)


def edgeLength(edge):
    vertices = mc.polyListComponentConversion(edge, toVertex=True)
    vertices = mc.filterExpand(vertices, sm=31)
    length = twoVerticesDistance(vertices[0], vertices[1])
    return length

def twoVerticesDistance(vertex1, vertex2):
    v1 = mc.pointPosition(vertex1, w=True)
    v2 = mc.pointPosition(vertex2, w=True)
    return _distance_3d(v1, v2)
    







###################################################################################################################################################
def cutter2NewMeshGrp():
    global sceneSize
    selCut = mc.ls(sl=1,l=1)
    if len(selCut) == 1:
        myType = checkInstType()
        if myType[1] != 'new':
            instBake()
            selCut = mc.ls(sl=1,l=1)
        getOPType = mc.getAttr(selCut[0]+'.cutterOp')
        if getOPType != 'union':
            #create new box shape by adding all union cutter and base mesh
            meshNameGrp = selCut[0].split('|')[1]
            meshName = meshNameGrp.replace('BoolGrp','')
            dulMesh = mc.duplicate(meshName, rr = True, un=True)
            mc.parent(dulMesh,w=1)
            checkNumber = ''.join([n for n in selCut[0].split('|')[-1] if n.isdigit()])
            mc.rename(meshName + "bc" + str(checkNumber))
            shadowMesh = mc.ls(sl=1)
            checkBaseMeshList()
            mc.select(shadowMesh)
            setCutterBaseMesh()
            updateVisLayer()
            mc.polyCube(w = sceneSize, h= sceneSize, d= sceneSize ,sx =1 ,sy= 1, sz= 1)
            mc.rename(shadowMesh[0]+'_myInter')
            mc.delete(ch=1)
            mc.parent(shadowMesh[0]+'_myInter', shadowMesh[0] + 'BoolGrp')
            mc.connectAttr((selCut[0]+'.outMesh'), (shadowMesh[0]+'_myInter.inMesh'),f=True)
            mc.connectAttr((selCut[0]+'.translate'), (shadowMesh[0]+'_myInter.translate'),f=True)
            mc.connectAttr((selCut[0]+'.rotate'), (shadowMesh[0]+'_myInter.rotate'),f=True)
            mc.connectAttr((selCut[0]+'.scale'), (shadowMesh[0]+'_myInter.scale'),f=True)
            mc.select(shadowMesh[0]+'_myInter')
            mc.ReversePolygonNormals()
            history = mc.listHistory(shadowMesh[0]+'_myInter')
            if history:
                poly_normal_nodes = mc.ls(history, type='polyNormal')
                mc.rename(shadowMesh[0]+'_myInterRN')
                mc.rename(poly_normal_nodes[0], shadowMesh[0]+'_RN')
                mc.setAttr(shadowMesh[0]+'_myInterRN.visibility',0)
            mc.connectAttr((shadowMesh[0]+'_myInterRNShape.outMesh'), (shadowMesh[0]+'_myCut.inputPoly[1]'),f=True)
            mc.connectAttr((shadowMesh[0]+'_myInterRNShape.worldMatrix[0]'), (shadowMesh[0]+'_myCut.inputMat[1]'),f=True)
            mc.select(selCut)
            mc.sets(name = (shadowMesh[0] + 'Shadow'), text= (shadowMesh[0] + 'Shadow'))
            showAllCutter()
            baseMeshColorUpdate()

        else:
            mc.warning('SpeedCut: Only works for difference or intersection cutters.')
    else:
        mc.warning('SpeedCut: Please select one cutter only.')


def fixShadowLink():
    listAllShadow = mc.ls('*Shadow')
    #l = listAllShadow[0]
    for l in listAllShadow:
        checkNodeType = mc.nodeType(l)
        if checkNodeType == 'objectSet':
            shadowName = mc.sets(l,q=1)
            targetName = l.replace('Shadow','')
            if mc.objExists((targetName +'BoolGrp')) == 0:
                mc.delete(l)
            else:
                cutterShapeNode = mc.listRelatives(shadowName[0], s=True, f=True )
                shapes = mc.listRelatives((targetName+'_bool'), shapes=True)
                shadeEng = mc.listConnections(shapes , type = 'shadingEngine')
                materials = mc.ls(mc.listConnections(shadeEng ), materials = True)
                if mc.objExists(targetName +'_myInterRN'):
                    mc.setAttr(targetName +'_myInterRN.visibility',0) 
                    if mc.objExists(targetName +'_myCut'):
                        mc.connectAttr((targetName +'_myInterRNShape.outMesh'), (targetName +'_myCut.inputPoly[1]'),f=True)
                        mc.connectAttr((targetName +'_myInterRNShape.worldMatrix[0]'), (targetName+'_myCut.inputMat[1]'),f=True)
                if mc.objExists(targetName +'_RN'):
                    mc.connectAttr((cutterShapeNode[0]+'.outMesh'), (targetName+'_RN.inputPolymesh'),f=True)
                                 
                if mc.objExists(targetName+'_ShaderSG'):
                    mc.sets((targetName+'_bool'), e=True, forceElement = (targetName+'_ShaderSG'))



###################################################################################################################################################

def deSelect():
    obj_shape = mc.listRelatives(parent=True, f=True)
    obj = mc.listRelatives(obj_shape,parent=True, f=True)
    mc.select(obj)
    mc.selectMode(leaf=True)
    cmd = "changeSelectMode -object;"
    mel.eval(cmd)
    mc.select(clear=True)

def instDistanceUpdate():
    myType = checkInstType()
    if myType[1] != 'new':
        checkMaster = myType[0]
        checkDis =  mc.floatSliderGrp('disSlider',q=True, v = True  )
        checkState = mc.attributeQuery('arrayOffset',node = checkMaster,ex=True)
        if checkState == 1:
            mc.setAttr((checkMaster+'.arrayOffset'),checkDis)


def instReNew():
    myType = checkInstType()
    if myType[1] != 'new':
        instRemove()
        checkMaster = myType[0]
        currentDir = mc.getAttr(checkMaster+'.arrayDirection')

        if myType[1] == 'linear':
            instLinearAdd(currentDir)
        else:
            instRadAdd(currentDir)

def instTypeToggle():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    currentSel =mc.ls(sl=1,fl=1)
    if len(currentSel) == 1:
        #case one Linear to Radial
        myType = checkInstType()
        if myType[1] != 'new':
            getNumber = mc.getAttr(myType[0]+'.arrayNumber')
            getDis = mc.getAttr(myType[0]+'.arrayOffset')
            getDir = mc.getAttr(myType[0]+'.arrayDirection')
            mc.intSliderGrp('instNumSlider', e=True,  v = getNumber)
            mc.floatSliderGrp('disSlider',e=True, v = getDis)
            if myType[1] == 'linear':
                instRemove()
                instRadAdd(getDir)

            elif myType[1] == 'radial':
                removeRadArray()
                instLinearAdd(getDir)


def instLinearAdd(direction):
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if len(beseMesh) > 0:
            selCutterCheck = mc.ls(sl=1, fl=1, l=1, type='transform')
            if 'boxCutter' in selCutterCheck[0]:
                mc.button('arrayLinear',e=True, bgc = [0.3, 0.5, 0.6] )
                mc.button('arrayRadial',e=True, bgc = [0.28,0.28,0.28])
                myType = checkInstType()
                instRemove()
                dir = direction
                arraySample = mc.ls(sl=1,fl=1)
                sourcePivot = mc.xform(arraySample[0], q=1, ws=1 ,rp=1)
                if 'boxCutter' in arraySample[0] and len(arraySample)==1:
                    bbox= mc.xform(arraySample[0], q=1, ws=1, bb=1)
                    myLength = []
                    myLength = _bbox_axis_length(bbox, dir)
    
                    getIntNumber = []
                    getDist = []
    
                    if myType[1] == 'new':
                        getIntNumber = 2
                        getDist = 1.5
                        mc.intSliderGrp('instNumSlider', e=True,  v = 2)
                        mc.floatSliderGrp('disSlider',e=True, v = 1.5)
                    else:
                        getIntNumber = mc.intSliderGrp('instNumSlider', q=True,  v = True)
                        checkState = mc.attributeQuery('arrayOffset',node = myType[0],ex=True)
                        if checkState == 1:
                            getDist = mc.getAttr(myType[0]+'.arrayOffset')
                            mc.floatSliderGrp('disSlider',e=True, v = getDist)
                    #create Attr
                    if not mc.attributeQuery('arrayNumber', node = arraySample[0], ex=True ):
                        mc.addAttr(arraySample[0], ln='arrayNumber')
    
                    if not mc.attributeQuery('arrayDirection', node = arraySample[0], ex=True ):
                        mc.addAttr(arraySample[0], ln='arrayDirection' ,dt= 'string')
    
                    if not mc.attributeQuery('arrayType', node = arraySample[0], ex=True ):
                        mc.addAttr(arraySample[0], ln='arrayType',dt= 'string')
    
                    if not mc.attributeQuery('arrayLength', node = arraySample[0], ex=True ):
                        mc.addAttr(arraySample[0], ln='arrayLength')
    
                    if not mc.attributeQuery('arrayOffset', node = arraySample[0], ex=True ):
                        mc.addAttr(arraySample[0], ln='arrayOffset')
    
                    if not mc.attributeQuery('arrayMaster', node = arraySample[0], ex=True ):
                        mc.addAttr(arraySample[0], ln='arrayMaster'  ,dt= 'string')
                        mc.setAttr((arraySample[0]+'.arrayOffset'),1)
    
                    mc.setAttr((arraySample[0]+'.arrayNumber'),getIntNumber)
                    mc.setAttr((arraySample[0]+'.arrayDirection'),dir,type="string")
                    mc.setAttr((arraySample[0]+'.arrayType'),'linear',type="string")
                    mc.setAttr((arraySample[0]+'.arrayLength'),myLength)
                    mc.setAttr((arraySample[0]+'.arrayMaster'),arraySample[0],type="string")
    
                    dirA = (arraySample[0]+'.translate'+dir)
                    collections=[]
    
                    for i in range(getIntNumber-1):
                        newIns = mc.instance(arraySample[0])
                        collections.append(newIns[0])
                        if not mc.attributeQuery('arrayOrder', node = newIns[0], ex=True ):
                            mc.addAttr(newIns[0], ln='arrayOrder')
                        mc.setAttr((newIns[0]+'.arrayOrder'),(i+1))
                        mc.setAttr((arraySample[0] + '.arrayOffset'),getDist)
                        cmdTextA = (newIns[0] + '.translate' + dir + '= ' + arraySample[0] + '.arrayLength *' + arraySample[0] + '.arrayOffset *' +  newIns[0] + '.arrayOrder +'+ dirA +';')
                        mc.expression( s = cmdTextA, o = newIns[0], ae = True, uc = all)
                        attrList = {'translateX','translateY','translateZ','rotateX','rotateY','rotateZ','scaleX','scaleY','scaleZ'}
                        attrList.remove(('translate' + str(dir)))
                        for a in attrList:
                            mc.connectAttr((arraySample[0]+'.' + a), (newIns[0] + '.' + a),f=True)
                    parent = mc.listRelatives(arraySample[0], p=True )
                    if not 'ArrayGrp' in parent[0]:
                        mc.group(arraySample[0],collections)
                        mc.rename(arraySample[0]+'ArrayGrp')
    
                    mc.xform((arraySample[0]+'ArrayGrp') ,ws=1, piv = (sourcePivot[0],sourcePivot[1],sourcePivot[2]))
                    mc.setAttr( (arraySample[0]+".arrayNumber"),getIntNumber)
                    mc.setAttr( (arraySample[0]+".arrayOffset"),getDist)
                    mc.select((arraySample[0]+'ArrayGrp'))
                    fixBoolNodeConnection()


def toggleArrayType():
    #toggle existing pattern
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        currentSel =mc.ls(sl=1,fl=1)
        linearActive = _is_button_active('arrayLinear')
        if len(currentSel) == 1:
            myType = checkInstType()
            if myType[1] != 'new':
                getNumber = mc.getAttr(myType[0]+'.arrayNumber')
                getDis = mc.getAttr(myType[0]+'.arrayOffset')
                getDir = mc.getAttr(myType[0]+'.arrayDirection')
                getGap = mc.getAttr(myType[0]+'.panelGap')
                mc.intSliderGrp('instNumSlider', e=True,  v = getNumber)
                mc.floatSliderGrp('disSlider',e=True, v = getDis)
                mc.floatSliderGrp('gapSlider',e=True, v = getGap)
                if (checkState[0] < 0.285):
                    removeRadArray()
                    instLinearAdd(getDir)
    
                else:
                    instRemove()
                    instRadAdd(getDir)
    
    
        if (checkState[0] < 0.285):
            mc.button('arrayRadial' ,e=True, bgc = [0.28,0.28,0.28])
            mc.button('arrayLinear', e=True, bgc = [0.3, 0.5, 0.6] )
        else:
            mc.button('arrayRadial' ,e=True, bgc = [0.3, 0.5, 0.6] )
            mc.button('arrayLinear', e=True, bgc = [0.28,0.28,0.28])


def arrayPattrn(dir):
    if _is_button_active('arrayLinear'):#Linear
        instLinearAdd(dir)
    else:
        instRadAdd(dir)

def checkInstType():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != NO_BASE_MESH:
        arraySample = []
        checkGrp = mc.ls(sl=1,fl=1,l=1)
        if checkGrp:
            if 'ArrayGrp' in checkGrp[0]:
                mc.connectControl('disSlider', (''))
                allChild = mc.listRelatives(checkGrp[0], ad=True)
                getShapeNode = mc.ls(allChild,type ='shape')
                listTransNode = mc.listRelatives(getShapeNode,  p=True )
                arraySample = listTransNode
                checkMaster = mc.getAttr(arraySample[0]+'.arrayMaster')
                checkMasterType = mc.getAttr(arraySample[0]+'.arrayType')
                mc.floatSliderGrp('disSlider',e=True, en= True )
                mc.intSliderGrp('instNumSlider',e=True, en= True )
                return (checkMaster,checkMasterType)
            else:
                if mc.attributeQuery('arrayMaster', node = checkGrp[0], ex=True ):
                    checkMaster = mc.getAttr(checkGrp[0]+'.arrayMaster')
                    checkMasterType = mc.getAttr(checkGrp[0]+'.arrayType')
                    if checkMasterType != None:
                        return (checkMaster,checkMasterType)
                else:
                    return ('new','new')


def removeArrayGrp():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selCutterCheck = mc.ls(sl=1, fl=1, l=1, type='transform')
        if len(selCutterCheck) == 1 and 'boxCutter' in selCutterCheck[0] and 'ArrayGrp' in selCutterCheck[0]:
            myType = checkInstType()
            mc.select(myType[0])
            if myType[1] == 'radial':
                removeRadArray()
            elif myType[1] == 'linear':
                instRemove()
                mc.parent(myType[0],(beseMesh +'_cutterGrp'))
                mc.delete(myType[0]+'ArrayGrp')
            mc.setAttr((myType[0]+'.arrayType'),'new',type="string")
            mc.setAttr((myType[0]+'.arrayMaster'),'new',type="string")


def instRadAdd(direction):
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selCutterCheck = mc.ls(sl=1, fl=1, l=1, type='transform')
        if len(beseMesh) > 0:
            if 'boxCutter' in selCutterCheck[0] :
                mc.button('arrayLinear',e=True, bgc = [0.28,0.28,0.28])
                mc.button('arrayRadial',e=True, bgc = [0.3, 0.5, 0.6])
                myType = checkInstType()
                removeArrayGrp()
                arraySample = mc.ls(sl=1,fl=1)
                dir = direction
                getIntNumber = []
                getDist = []
    
                if myType[1] == 'new':
                    getIntNumber = 3
                    getDist = 1
                    mc.intSliderGrp('instNumSlider', e=True,  v = 3)
                    mc.floatSliderGrp('disSlider',e=True, v = 1)
                else:
                    getIntNumber = mc.intSliderGrp('instNumSlider', q=True,  v = True)
                    checkState = mc.attributeQuery('arrayOffset',node = myType[0],ex=True)
                    if checkState == 1:
                        getDist = mc.getAttr(myType[0]+'.arrayOffset')
                        mc.floatSliderGrp('disSlider',e=True, v = getDist)
                collection =[]
    
                #create Attr
                if not mc.attributeQuery('arrayNumber', node = arraySample[0], ex=True ):
                    mc.addAttr(arraySample[0], ln='arrayNumber')
    
                if not mc.attributeQuery('arrayDirection', node = arraySample[0], ex=True ):
                    mc.addAttr(arraySample[0], ln='arrayDirection' ,dt= 'string')
    
                if not mc.attributeQuery('arrayType', node = arraySample[0], ex=True ):
                    mc.addAttr(arraySample[0], ln='arrayType',dt= 'string')
    
                if not mc.attributeQuery('arrayOffset', node = arraySample[0], ex=True ):
                    mc.addAttr(arraySample[0], ln='arrayOffset')
    
                if not mc.attributeQuery('arrayMaster', node = arraySample[0], ex=True ):
                    mc.addAttr(arraySample[0], ln='arrayMaster'  ,dt= 'string')
                    mc.setAttr((arraySample[0]+'.arrayOffset'),1)
                if not mc.attributeQuery('arrayLength', node = arraySample[0], ex=True ):
                        mc.addAttr(arraySample[0], ln='arrayLength')
    
                mc.setAttr((arraySample[0]+'.arrayNumber'),getIntNumber)
                mc.setAttr((arraySample[0]+'.arrayOffset'),getDist)
                mc.setAttr((arraySample[0]+'.arrayDirection'),dir,type="string")
                mc.setAttr((arraySample[0]+'.arrayType'),'radial',type="string")
                mc.setAttr((arraySample[0]+'.arrayMaster'),arraySample[0],type="string")
    
                bbox= mc.xform(arraySample[0], q=1, ws=1, bb=1)
                length = _bbox_diagonal(bbox)
                mc.setAttr((arraySample[0]+'.arrayLength'),length)
    
                sourcePivot = mc.xform(arraySample[0], q=1, ws=1 ,rp=1)
    
                rAngle = 360.0 / getIntNumber
                #inst
                collection = []
                for i in range(getIntNumber-1):
                    mc.select(arraySample[0])
                    mc.instance()
                    newNode = mc.ls(sl=True)
                    mc.select(newNode)
                    mc.group()
                    mc.rename(newNode[0]+'_Trans')
                    mc.group()
                    mc.rename(newNode[0]+'_Rot')
                    collection.append(newNode[0]+'_Rot')
                    mc.xform((newNode[0]+'_Rot') ,ws=1, piv = (sourcePivot[0],sourcePivot[1],sourcePivot[2]))
                    if dir == 'X':
                        mc.rotate((rAngle*(i)+rAngle), 0 ,0, r=True, ws=True, fo=True)
                    elif dir == 'Y':
                        mc.rotate(0,(rAngle*(i)+rAngle),0, r=True, ws=True, fo=True)
                    else:
                        mc.rotate(0,0,(rAngle*(i)+rAngle), r=True, ws=True, fo=True)
                # group master
                mc.select(arraySample[0])
                mc.group()
                mc.rename(arraySample[0]+'_Trans')
                mc.group()
                mc.rename(arraySample[0]+'_Rot')
                collection.append(arraySample[0]+'_Rot')
                mc.xform((arraySample[0]+'_Rot') ,ws=1, piv = (sourcePivot[0],sourcePivot[1],sourcePivot[2]))
    
                mc.select(collection)
                mc.group()
                mc.rename(arraySample[0]+'ArrayGrp')
                OffsetDir =[]
    
                if dir == 'X':
                    OffsetDir = 'Y'
                elif dir == 'Y':
                   OffsetDir = 'X'
                else:
                  OffsetDir = 'X'
    
                for c in collection:
                    cutterName = c.replace('_Rot', '')
                    cmdTextA = (cutterName + '_Trans.translate' + OffsetDir + '= ' + arraySample[0] + '.arrayLength *' + arraySample[0] + '.arrayOffset;')
                    mc.expression( s = cmdTextA, o = (arraySample[0] + '_Trans.translate'), ae = True, uc = all)
                    mc.select((arraySample[0]+'ArrayGrp'))
                    mc.xform((arraySample[0]+'ArrayGrp') ,ws=1, piv = (sourcePivot[0],sourcePivot[1],sourcePivot[2]))
                    attrList = {'translateX','translateY','translateZ','rotateX','rotateY','rotateZ','scaleX','scaleY','scaleZ'}
                    if cutterName != arraySample[0]:
                        for a in attrList:
                            mc.connectAttr((arraySample[0]+'.' + a), (cutterName + '.' + a),f=True)
    
                mc.setAttr( (arraySample[0]+".arrayNumber"),getIntNumber)
                mc.setAttr( (arraySample[0]+".arrayOffset"),getDist)
                fixBoolNodeConnection()

def removeRadArray():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        boolNode = mc.listConnections(mc.listHistory((beseMesh +'_bool'),f=1),type='polyCBoolOp')
        myType = checkInstType()
        if myType[1] == 'radial':
            arraySample = myType[0]
            if mc.objExists(arraySample+'_Rot*'):
                mc.select(arraySample+'_Rot*')
                listRArray = mc.ls(sl=1,fl=1)
                mc.delete(listRArray[1:len(listRArray)])
                mc.parent(arraySample,beseMesh+'_cutterGrp')
                sourcePivot = mc.xform((arraySample+'_Rot'), q=1, ws=1 ,rp=1)
                mc.select(arraySample)
                mc.move( sourcePivot[0],sourcePivot[1],sourcePivot[2],rpr=True)
                if mc.objExists(arraySample+'ArrayGrp'):
                    mc.delete(arraySample+'ArrayGrp')
            if mc.objExists(arraySample+'ArrayGrp'):
                mc.delete(arraySample+'ArrayGrp')
    
            shapeNode = mc.listRelatives(arraySample, s=True )
            listConnect = mc.connectionInfo((shapeNode[0]+'.outMesh'), dfs=True )
            if len(listConnect)>0:
                for a in listConnect:
                    mc.disconnectAttr((shapeNode[0]+'.outMesh'), a)
            checkNumber = ''.join([n for n in arraySample.split('|')[-1] if n.isdigit()])
            mc.connectAttr( (shapeNode[0]+".outMesh"), ((boolNode[0]+'.inputPoly['+str(checkNumber)+']')),f=True)
            mc.connectAttr( (shapeNode[0]+".worldMatrix[0]"), ((boolNode[0]+'.inputMat['+str(checkNumber)+']')),f=True)
            mc.select(arraySample)

def instBake():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        checkSel = mc.ls(sl=True)
        if len(checkSel) > 0:
            myType = checkInstType()
            if myType[1] != 'new':
                opType = mc.getAttr(myType[0]+'.cutterOp')
                arraySample = myType[0]
                sourcePivot = mc.xform((arraySample+'ArrayGrp'), q=1, ws=1 ,rp=1)
                mc.select(arraySample+'ArrayGrp')
                mc.select(hi=True)
                mc.select(arraySample,d=True)
                mc.select((arraySample+'ArrayGrp'),d=True)
                cutterList = mc.ls('boxCutter*',sl=True,type='transform')
                mc.select(arraySample)
                mc.ConvertInstanceToObject()
                if myType[1] == 'radial':
                    mc.parent(arraySample,(arraySample+'ArrayGrp'))
                unInstanceMesh = mc.ls(sl=1,fl=1, l=1)
                for c in cutterList:
                    if '_Rot' not in c and '_Trans' not in c and 'ArrayGrp' not in c:
                        if myType[1] == 'radial':
                            mc.parent(c , (arraySample + 'ArrayGrp'))
                        mc.select(arraySample,r=True)
                        mc.duplicate()
                        newNode=mc.ls(sl=True)
                        mc.select(c,add=1)
                        mc.matchTransform(pos =True,rot=True)
                        mc.delete(c)
                        mc.rename(newNode,c)
                for c in cutterList:
                    if '_Rot' in c :
                        mc.delete(c)
                mc.select(arraySample+'ArrayGrp')
                mc.select(hi=True)
                mc.select((arraySample+'ArrayGrp'),d=True)
                listNew = mc.ls('boxCutter*',sl=True,type='transform')
                for n in listNew:
                    mc.rename(n,'tempCutter01')
                listBake=mc.ls('tempCutter*',s=1)
                while len(listBake) > 1:
                    mc.polyCBoolOp(listBake[0], listBake[1], op=1, ch=1, preserveColor=0, classification=1, name=listBake[0])
                    mc.DeleteHistory()
                    if mc.objExists(listBake[1]):
                        mc.delete(listBake[1])
                    mc.rename(listBake[0])
                    listBake.remove(listBake[1])
                #in case cutterGrp will get delete when delete history
                if mc.objExists((beseMesh +'_cutterGrp')) == 0:
                    mc.CreateEmptyGroup()
                    mc.rename((beseMesh +'_cutterGrp'))
                    mc.parent((beseMesh +'_cutterGrp'),(beseMesh +'BoolGrp'))
                mc.select(listBake[0])
                useOwnCutterShape()
                newCutter = mc.ls(sl=True, fl=True)
                mc.rename(newCutter[0],arraySample)
                mc.xform(arraySample ,ws=1, piv = (sourcePivot[0],sourcePivot[1],sourcePivot[2]))
                if mc.objExists(arraySample+'ArrayGrp'):
                    mc.delete(arraySample+'ArrayGrp')
                    mc.ogs(reset =1)
                if not mc.attributeQuery('cutterOp', node = arraySample, ex=True ):
                    mc.addAttr(arraySample, ln='cutterOp',  dt= 'string')
                mc.setAttr((arraySample+'.cutterOp'),e=True, keyable=True)
                mc.setAttr((arraySample+'.cutterOp'),opType,type="string")
                mc.select(arraySample)
                fixBoolNodeConnection()
        else:
            print ('nothing selected!')

def instRemove():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        myType = checkInstType()
        if myType[1] == 'linear':
            arraySample = myType[0]
            listA = mc.listConnections(arraySample,type = 'expression')
            if listA != None:
                listA = set(listA)
                collectInst=[]
                for l in listA:
                    checkConnection = mc.connectionInfo( (l+'.output[0]'), dfs=True)
                    mesh = checkConnection[0].split(".")[0]
                    collectInst.append(mesh)
                mc.delete(collectInst)
            shapeNode = mc.listRelatives(arraySample, s=True )
            listConnect = mc.connectionInfo((shapeNode[0]+'.outMesh'), dfs=True )
            if len(listConnect)>0:
                for a in listConnect:
                    mc.disconnectAttr((shapeNode[0]+'.outMesh'), a)
            checkNumber = ''.join([n for n in arraySample.split('|')[-1] if n.isdigit()])
            if mc.objExists(beseMesh + '_mySubs') == 0:
                restoreCutterWithSymmtry()
    
            setType = mc.getAttr(arraySample+'.cutterOp')
    
            mc.connectAttr( (shapeNode[0]+".outMesh"), ((beseMesh +'_my' + setType.title() + '.inputPoly['+str(checkNumber)+']')),f=True)
            mc.connectAttr( (shapeNode[0]+".worldMatrix[0]"), ((beseMesh +'_my' + setType.title() +'.inputMat['+str(checkNumber)+']')),f=True)
            mc.select(arraySample)
            checkGap = mc.getAttr(arraySample + '.panelGap')
            if checkGap > 0:
                makeGap()
                mc.floatSliderGrp('gapSlider',e=True, en= True,v=checkGap )

#######################################################################################################################################################################################
#######################################################################################################################################################################################




def moveRightItem():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selListRight = mc.textScrollList('bevelList', q=True, si=True)
        checkState = mc.iconTextButton('visRight', q = True , image1 = True)
        if selListRight != None:
            if len(selListRight) > 0:
                mc.textScrollList('nonBevelList',edit = True, da = True)
                for s in selListRight:
                    mc.textScrollList('bevelList',edit = True, ri = s)
                    mc.textScrollList('nonBevelList',edit = True, si = s, append = s)
                sortBevelList()
                for s in selListRight:
                    mc.textScrollList('nonBevelList',edit = True, si = s)
                    longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + s
                    if checkState == 'nodeGrapherSoloed.svg':
                        mc.setAttr((longName + '.visibility'), 1)
                    else:
                        mc.setAttr((longName + '.visibility'), 0)
                    mc.setAttr((longName+'.preBevel'),0)

def moveLeftItem():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selListLeft = mc.textScrollList('nonBevelList', q=True, si=True)
        checkState = mc.iconTextButton('visLeft', q = True , image1 = True)
        if selListLeft != None:
            if len(selListLeft) > 0:
                mc.textScrollList('bevelList',edit = True, da = True)
                for s in selListLeft:
                    mc.textScrollList('nonBevelList',edit = True, ri = s)
                    mc.textScrollList('bevelList',edit = True, si = s ,append = s)
                sortBevelList()
                for s in selListLeft:
                    mc.textScrollList('bevelList',edit = True, si = s)
                    longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + s
                    if checkState == 'nodeGrapherSoloed.svg':
                        mc.setAttr((longName + '.visibility'), 1)
                    else:
                        mc.setAttr((longName + '.visibility'), 0)
                    mc.setAttr((longName+'.preBevel'),1)


def reselctList():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        currentSel = mc.ls(sl=True,l=True)
        mc.textScrollList('nonBevelList', e=True, da=True)
        selListRight = mc.textScrollList('nonBevelList', q=True, ai=True)
        if selListRight != None:
            for c in currentSel:
                shortName = c.split('|')[-1]
                for s in selListRight:
                    if shortName == s:
                        mc.textScrollList('nonBevelList',edit = True, si = shortName)
    
        mc.textScrollList('bevelList', e=True, da=True)
        selListLeft = mc.textScrollList('bevelList', q=True, ai=True)
        if selListLeft != None:
            for c in currentSel:
                shortName = c.split('|')[-1]
                for s in selListLeft:
                    if shortName == s:
                        mc.textScrollList('bevelList',edit = True, si = shortName)


def togglevisLeft():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        checkState = mc.iconTextButton('visLeft', q = True , image1 = True)
        selListLeft = mc.textScrollList('bevelList', q=True, ai=True)
        if checkState == 'nodeGrapherSoloed.svg':
            mc.iconTextButton('visLeft', e = True , image1 = 'circle.png')
            if selListLeft != None and len(selListLeft) > 0:
                for s in selListLeft:
                    longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + s
                    mc.setAttr((longName + '.visibility'), 0)
        else:
            mc.iconTextButton('visLeft', e = True , image1 = 'nodeGrapherSoloed.svg')
            if selListLeft != None and len(selListLeft) > 0:
                for s in selListLeft:
                    longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + s
                    mc.setAttr((longName + '.visibility'), 1)

def togglevisRight():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        checkState = mc.iconTextButton('visRight', q = True , image1 = True)
        selListRight = mc.textScrollList('nonBevelList', q=True, ai=True)
        if checkState == 'nodeGrapherSoloed.svg':
            mc.iconTextButton('visRight', e = True , image1 = 'circle.png')
            if selListRight != None and len(selListRight) > 0:
                for s in selListRight:
                    longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + s
                    mc.setAttr((longName + '.visibility'), 0)
        else:
            mc.iconTextButton('visRight', e = True , image1 = 'nodeGrapherSoloed.svg')
            if selListRight != None and len(selListRight) > 0:
                for s in selListRight:
                    longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + s
                    mc.setAttr((longName + '.visibility'), 1)


def selBevelList():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selList = mc.textScrollList('bevelList', q=True, si=True)
        mc.textScrollList('nonBevelList',edit = True, da = True)
        longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + selList[0]
        mc.select(longName, r=True)

def selNonBevelList():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selList = mc.textScrollList('nonBevelList', q=True, si=True)
        mc.textScrollList('bevelList',edit = True, da = True)
        longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + selList[0]
        mc.select(longName, r=True)


def visListOn():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selListLeft = mc.textScrollList('bevelList', q=True, ai=True)
        mc.iconTextButton('visLeft', e = True , image1 = 'nodeGrapherSoloed.svg')
        if selListLeft != None and len(selListLeft) > 0:
            for s in selListLeft:
                longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + s
                mc.setAttr((longName + '.visibility'), 1)
    
        selListRight = mc.textScrollList('nonBevelList', q=True, ai=True)
        mc.iconTextButton('visRight', e = True , image1 = 'nodeGrapherSoloed.svg')
        if selListRight != None and len(selListRight) > 0:
            for s in selListRight:
                longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + s
                mc.setAttr((longName + '.visibility'), 1)
        mc.setAttr((beseMesh+'_bakeStep.visibility'),1)


def visListOff():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selListLeft = mc.textScrollList('bevelList', q=True, ai=True)
        mc.iconTextButton('visLeft', e = True , image1 = 'circle.png')
        if selListLeft != None and len(selListLeft) > 0:
            for s in selListLeft:
                longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + s
                mc.setAttr((longName + '.visibility'), 0)
    
        selListRight = mc.textScrollList('nonBevelList', q=True, ai=True)
        mc.iconTextButton('visRight', e = True , image1 = 'circle.png')
        if selListRight != None and len(selListRight) > 0:
            for s in selListRight:
                longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + s
                mc.setAttr((longName + '.visibility'), 0)
        mc.setAttr((beseMesh+'_bakeStep.visibility'),1)



def loadBevelList():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        bakeList = mc.ls('bakeCutter*',type='transform',l=True)
        if len(list) > 0:
            cleanList = []
            for l in list:
                if beseMesh in l:
                    cleanList.append(l)
            mc.textScrollList('bevelList',edit = True, ra = True)
            mc.textScrollList('nonBevelList',edit = True, ra = True)
            for c in cleanList:
                shortName = c.split('|')[-1]
                checkState = mc.getAttr(c+'.preBevel')
                if checkState == 1:
                    mc.textScrollList('bevelList',edit = True, append = shortName)
                else:
                    mc.textScrollList('nonBevelList',edit = True, append = shortName)
    


def publishFinal():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if len(beseMesh) > 0:
            if mc.objExists(beseMesh + '_publishMesh'):
                print ('publishMesh existed!')
    
            else:
                if mc.objExists(beseMesh + '_preBevelMeshFinal'):
                    newNode = mc.duplicate((beseMesh + '_preBevelMeshFinal'),rr = True, un=True)
                    mc.rename(newNode[0],(beseMesh + '_publishMesh'))
                    mc.parent((beseMesh + '_publishMesh'),w=True)
                    mc.DeleteHistory()
                    mc.setAttr((beseMesh+ 'BoolGrp.visibility'),0)
                else:
                    if mc.objExists(beseMesh + '_preBaseMesh'):
                        newNode = mc.duplicate((beseMesh + '_preBaseMesh'),rr = True, un=True)
                        mc.rename(newNode[0],(beseMesh + '_publishMesh'))
                        mc.parent((beseMesh + '_publishMesh'),w=True)
                        mc.DeleteHistory()
                        mc.setAttr((beseMesh+ 'BoolGrp.visibility'),0)
                    else:
                        print ('nothing to publish')


def preCheckBevelByVolumn():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        bbox = mc.xform(beseMesh, q=True, ws=True, bbi=True)
        disX =  math.sqrt((bbox[3] - bbox[0])*(bbox[3] - bbox[0]))
        disY =  math.sqrt((bbox[4] - bbox[1])*(bbox[4] - bbox[1]))
        disZ =  math.sqrt((bbox[5] - bbox[2])*(bbox[5] - bbox[2]))
        baseVolumn = disX * disY *disZ
        guildVolumn = baseVolumn * 0.01 # 5% of base
        #check all cutter
        mc.select((beseMesh+'_bakeStep'), hi=True)
        mc.select((beseMesh+'_bakeStep'),d=True)
        mc.select((beseMesh+'_bakeBaseMesh'),d=True)
        sel = mc.ls(sl=1,fl=1,type='transform',l=True)
        mc.select(cl=True)
        for s in sel:
            checkState = mc.getAttr(s+'.statePanel')# skip if gap or panel
            if not mc.attributeQuery('preBevel', node = s, ex=True ):
                mc.addAttr(s, ln='preBevel', at = "float" )
                mc.setAttr((s+'.preBevel'), 0)
                checkStateBevel = mc.getAttr(s+'.preBevel')# already Made as non bevel
                if checkState == 0 and checkStateBevel == 1 :
                    bbox = mc.xform(s, q=True, ws=True, bbi=True)
                    disX =  math.sqrt((bbox[3] - bbox[0])*(bbox[3] - bbox[0]))
                    disY =  math.sqrt((bbox[4] - bbox[1])*(bbox[4] - bbox[1]))
                    disZ =  math.sqrt((bbox[5] - bbox[2])*(bbox[5] - bbox[2]))
                    volumn = disX * disY *disZ
                    if volumn < guildVolumn:
                        mc.setAttr((s+'.preBevel'), 0)
                    else:
                        mc.setAttr((s+'.preBevel'), 1)


def removeNonBevelList():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if len(beseMesh) > 0:
            removeLeftOver()
            mc.setAttr(beseMesh + '_preBevel.visibility',1)
            mc.rename((beseMesh + '_preBevel'),(beseMesh + '_preBaseMesh'))
            histList = mc.listHistory((beseMesh + '_preBaseMesh'))
            for l in histList:
                nodeTypeA = mc.nodeType(l)
                if nodeTypeA == 'polyBevel3':
                    mc.rename(l,(beseMesh+'_edgePreBevel'))
                elif  nodeTypeA == 'polyExtrudeFace':
                    mc.rename(l,(beseMesh+'_lcokFace'))
                else:
                    pass
            offsetV = mc.floatSliderGrp('offsetSliderPre',q=1, v =True)
            lockV = mc.floatSliderGrp('lockFaceSliderPre',q=1, v =True)
            segV = mc.intSliderGrp('segmentSliderPre',  q=1, v =True)
            miterV = mc.intSliderGrp('miteringSliderPre', q=1,v =True)
            mc.setAttr((beseMesh+'_lcokFace.offset'),lockV)
            mc.setAttr((beseMesh+'_edgePreBevel.segments'), segV)
            mc.setAttr((beseMesh+'_edgePreBevel.mitering'), miterV)
            mc.setAttr((beseMesh+'_edgePreBevel.offset'), offsetV)
            visListOff()
            outlineClean()
            mc.button('addPreBButton',e=True,en=False)
            mc.button('removePreBButton',e=True,en=True)
            mc.button('addPreNonBButton',e=True,en=True)
            mc.button('removePreNonBButton',e=True,en=False)
            mc.floatSliderGrp('lockFaceSliderPre',e=1, en=0)
            mc.floatSliderGrp('offsetSliderPre',e=1, en=1)
            mc.intSliderGrp('segmentSliderPre',e=1, en=1)
            mc.intSliderGrp('miteringSliderPre',e=1, en=1)
            mc.connectControl('segmentSliderPre', (beseMesh+'_edgePreBevel.segments'))
            mc.connectControl('miteringSliderPre',(beseMesh+'_edgePreBevel.mitering'))
            mc.connectControl('offsetSliderPre', (beseMesh+'_edgePreBevel.offset'))
            if mc.objExists(beseMesh + '_preBevelGrp'):
                mc.delete(beseMesh + '_preBevelGrp')
            mc.select((beseMesh + '_preBaseMesh'))

def addNonBevelList():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if mc.objExists(beseMesh + '_boolNonBevelUnion') == 0 or mc.objExists(beseMesh + '_boolNonBevelSubs') == 0 or mc.objExists(beseMesh + '_boolNonBevelCut') == 0:
            if len(beseMesh) > 0:
                boolPreNonBevel()
                visListOff()
                #outlineClean()
                mc.intSliderGrp('segmentSliderPre',e=True,en=True)
                mc.intSliderGrp('miteringSliderPre',e=True,en=True)
                mc.button('addPreBButton',e=True,en=False)
                mc.button('removePreBButton',e=True,en=True)
                mc.button('addPreNonBButton',e=True,en=False)
                mc.button('removePreNonBButton',e=True,en=True)
                mc.button('removeLockButton', e=1, en = 0)
                mc.button('removePreBButton', e=1, en = 0)
                mc.intSliderGrp('segmentSliderPre',e=1, en=0)
                mc.intSliderGrp('miteringSliderPre',e=1, en=0)

def rebuildPreview():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if len(beseMesh) > 0:
            preBevelNodes = mc.ls('*preBevel*')
            if preBevelNodes:
                mc.delete(preBevelNodes)
            preBaseNodes = mc.ls('*_preBaseMesh*')
            if preBaseNodes:
                mc.delete(preBaseNodes)
            boolNonNodes = mc.ls('*boolNon*')
            if boolNonNodes:
                mc.delete(boolNonNodes)
            mc.setAttr((beseMesh +'BoolGrp.visibility'),1)
            mc.setAttr((beseMesh +'_bool.visibility'),1)
            mc.button('addPreBButton',e=True,en=False)
            mc.button('removePreBButton',e=True,en=False)

def killPreview():
    rebuildPreview()
    restoreCutter()
    mc.button('addPreBButton',e=True,en=False)
    mc.button('removePreBButton',e=True,en=False)
    mc.button('addPreNonBButton',e=True,en=False)
    mc.button('removePreNonBButton',e=True,en=False)
    mc.button('removeLockButton',e=True,en=False)
    mc.button('addLockButton',e=True,en=False)
    mc.button('addCutButton',e=True,en=True)


    #if mc.window("jwSpeedCutBevelManger", exists = True):
    #    mc.deleteUI("jwSpeedCutBevelManger")


def preBevelUpdate():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if len(beseMesh) > 0:
            cutUpdate()
            lcokUpdate()
            addPreBevelEdgeRun()
            addNonBevelList()
            mc.floatSliderGrp('lockFaceSliderPre',e=1, en=1)
            mc.floatSliderGrp('offsetSliderPre', e=True, v = 1, min = 0.001, max = 1, fmx = 10)


def cutUpdate():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        offsetV = mc.floatSliderGrp('offsetSliderPre',q=1, v =True)
        lockV = mc.floatSliderGrp('lockFaceSliderPre',q=1, v =True)
        segV = mc.intSliderGrp('segmentSliderPre',  q=1, v =True)
        miterV = mc.intSliderGrp('miteringSliderPre', q=1,v =True)
        if len(beseMesh) > 0:
            loadBevelList()
            rebuildPreview()
            setPreBevelGrp()
            boolPreBevel()
            visListOff()
            #outlineClean()
            member = beseMesh + '_preBaseMesh'
            mc.select(beseMesh + '_preBaseMesh')
            mc.intSliderGrp('segmentSliderPre',e=True,en=False)
            mc.intSliderGrp('miteringSliderPre',e=True,en=False)
            mc.floatSliderGrp('lockFaceSliderPre',e=True,en=False)
            mc.floatSliderGrp('offsetSliderPre',e=True,en=False)
            mc.button('addLockButton',e=True,en=True)
            #Retop
            mc.polySelectConstraint(m=3,t=0x8000,sm=1)
            mc.polySelectConstraint(disable =True)
            triNode = mc.polyTriangulate(member,ch=0)
            quadNode = mc.polyQuad(member,a = 30, kgb = 0 ,ktb = 0, khe= 1, ws = 0, ch = 0)
            mc.delete(ch = True)
            #Clean
            mc.select(member)
            mergeNode = mc.polyMergeVertex( d = MERGE_VERTEX_TOLERANCE, ch = True)
            softNode = mc.polySoftEdge(angle=0.3)
            mel.eval("ConvertSelectionToEdges;")
            mc.polySelectConstraint(t=0x8000, m=3, sm=2)
            mc.polySelectConstraint(disable =True)
            selectEdges=mc.ls(sl=1,fl=1)
            if len(selectEdges)>0:
                mc.polyDelEdge(cv = True, ch = False)
            #Clean unused vertex points
            mc.select(member)
            mergeNode = mc.polyMergeVertex( d = MERGE_VERTEX_TOLERANCE, ch = True)
            mc.select(member)
            mc.ConvertSelectionToVertices()
            selected = mc.ls(sl=1, fl=1)
            mc.select(clear=True)
            for v in selected:
                if len( re.findall(r'\d+', mc.polyInfo(v,ve=True)[0]) ) == 3:
                    mc.select(v,add=True)
            mc.delete(mc.ls(sl=True))
            mc.select(member)
            softNode = mc.polySoftEdge(angle=30)
            #merge very close vertex by user
            mc.select(member)
            mc.delete(ch = True)
            mc.select(member)
            mergeNode = mc.polyMergeVertex( d = MERGE_VERTEX_TOLERANCE, ch = 0)
            mc.button('removeLockButton', e=1, en = 0)
            mc.select(member)
            mc.button('addLockButton', e=1, en = 1)

def bevelPreviewLockFace():
    global sourceFaces
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        member = beseMesh + '_preBaseMesh'
        mc.select(member)
        mc.polySelectConstraint(m=3,t=0x8000,sm=1)
        mc.polySelectConstraint(disable =True)
        hardEdges = mc.ls(sl=1,fl=1)
        mc.DetachComponent()
        listH = mc.listHistory(member, lv=0 )
        for h in listH:
            checkNode = mc.nodeType(h)
            if checkNode == 'polySplitEdge':
                mc.rename(h,'lockStart')
        mc.select(member)
        mc.ConvertSelectionToFaces()
        sourceFaces = mc.ls(sl=1,fl=1)
        offsetData = mc.floatSliderGrp('offsetSliderPre', q=1, v = 1)
        createSupportNode = mc.polyExtrudeFacet(sourceFaces, constructionHistory =1, keepFacesTogether = 1, divisions = 1, off = offsetData, smoothingAngle = 30)
        faceLockNode = mc.rename(createSupportNode[0], (beseMesh+'_lcokFace'))
        mc.GrowPolygonSelectionRegion()
        shapeExtrude = mc.ls(sl=1,fl=1)
        mc.select(member)
        mc.ConvertSelectionToFaces()
        mc.select(shapeExtrude,d=1 )
        mc.delete()
        mc.select(member)
        mc.polyMergeVertex(d = 0.001, ch = 1)
        mc.setAttr((faceLockNode + ".offset"), offsetData)
        mc.connectControl('lockFaceSliderPre', (faceLockNode + ".offset"))
        mc.setAttr((faceLockNode + ".offset"),0.1)
        mc.polySelectConstraint(m=3,t=0x8000,sm=1)
        mc.polySelectConstraint(disable =True)
        softNode = mc.polySoftEdge(angle= 180)
        mc.rename(softNode,'preSoftEdge')
        mc.select(cl=True)

def mergeHardEdgeVex():# vertices too close
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        member = beseMesh + '_preBaseMesh'
        mc.select(member)
        mc.polySelectConstraint(m=3,t=0x8000,sm=1)
        mc.polySelectConstraint(disable =True)
        mc.ConvertSelectionToVertices()
        mc.polyMergeVertex(d= 0.1,am= 1, ch= 1)

def smoothAroundLockEdge():#relax vertices surround lock edge then snap back to bool mesh to maintain shape
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        snapMesh = beseMesh + '_bool'
        global sourceFaces
        mc.select(sourceFaces)
        mel.eval('InvertSelection')
        mc.ConvertSelectionToVertices()
        tempSel=mc.ls(sl=1,fl=1)
        mc.GrowPolygonSelectionRegion()
        mc.select(tempSel, d=1 )
        mc.polyAverageVertex(i=10)
        mc.polyAverageVertex(i=10)
        mc.select(snapMesh,add=1)
        mc.transferAttributes(transferPositions =1, transferNormals= 0, transferUVs =0, transferColors= 2, sampleSpace = 0, searchMethod = 3, flipUVs = 0, colorBorders =0)
        mc.select(cl=1)

def bevelPreviewLockFaceRemove():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        member = beseMesh + '_preBaseMesh'
        mc.select(member)
        listH = mc.listHistory(member, lv=0 )
        for h in listH:
            checkNode = mc.nodeType(h)
            if checkNode != 'mesh':
                mc.delete(h)
                if 'lockStart' in h:
                    break
        mc.button('removeLockButton', e=1, en = 0)
        mc.button('addLockButton', e=1, en = 1)
        mc.button('addPreBButton', e=1, en = 0)
        mc.button('removePreBButton', e=1, en = 0)
        mc.button('addPreNonBButton', e=1, en = 0)
        mc.button('removePreNonBButton', e=1, en = 0)
        mc.connectControl('lockFaceSliderPre', (beseMesh + '_lcokFace.offset'))
        mc.select(member)
        softHardVis()

def lcokUpdate():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        offsetV = mc.floatSliderGrp('offsetSliderPre',q=1, v =True)
        lockV = mc.floatSliderGrp('lockFaceSliderPre',q=1, v =True)
        segV = mc.intSliderGrp('segmentSliderPre',  q=1, v =True)
        miterV = mc.intSliderGrp('miteringSliderPre', q=1,v =True)
        if len(beseMesh) > 0:
            bevelPreviewLockFace()
            mc.setAttr((beseMesh+'_lcokFace.offset'),lockV)
            visListOff()
            outlineClean()
            mc.select(beseMesh + '_preBaseMesh')
            mc.button('addPreBButton',e=True,en=True)
            mc.button('removePreBButton',e=True,en=False)
            mc.button('addPreNonBButton',e=True,en=False)
            mc.button('removePreNonBButton',e=True,en=False)
            mc.button('removeLockButton', e=1, en = 1)
            mc.button('addLockButton', e=1, en = 0)


def addPreBevelEdgeRun():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if mc.objExists(beseMesh +'_edgePreBevel') == 0:
            lockV = mc.floatSliderGrp('lockFaceSliderPre',q=1, v =True)
            addPreBevelEdge()
            visListOff()
            outlineClean()
            mc.button('addPreBButton',e=True,en=False)
            mc.button('removePreBButton',e=True,en=True)
            mc.floatSliderGrp('lockFaceSliderPre',e=True,en=False)
            mc.floatSliderGrp('offsetSliderPre',e=True,en=True , max = lockV)
            mc.button('addPreNonBButton',e=True,en=True)
            mc.button('removePreNonBButton',e=True,en=False)
            mc.button('addLockButton',e=True,en=False)
            mc.setAttr((beseMesh+'_edgePreBevel.offset'),lockV)
            mc.select(beseMesh + '_preBaseMesh')
            mc.TogglePolyDisplayEdges()
            mc.button('removeLockButton',e=1, en=0)


def removePreBevelEdgeRun():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        mc.delete(beseMesh + '_preBaseMesh')
        mc.showHidden(beseMesh + '_preBaseLock')
        mc.rename((beseMesh + '_preBaseLock') ,(beseMesh + '_preBaseMesh'))
        outlineClean()
        mc.button('addPreBButton',e=True,en=True)
        mc.button('removePreBButton',e=True,en=False)
        mc.floatSliderGrp('lockFaceSliderPre',e=True,en=True)
        mc.floatSliderGrp('offsetSliderPre',e=True,en=False)
        mc.button('addPreNonBButton',e=True,en=False)
        mc.button('removePreNonBButton',e=True,en=False)
        mc.button('removeLockButton', e=1, en = 0)
        mc.button('addLockButton', e=1, en = 0)
        mc.button('removeLockButton', e=1, en = 1)
        mc.select(beseMesh + '_preBaseMesh')
        listH = mc.listHistory((beseMesh + '_preBaseMesh'), lv=0 )
        for l in listH:
            checkType=mc.nodeType(l)
            if  checkType == "polyExtrudeFace":
                mc.connectControl('lockFaceSliderPre', (l + ".offset"))


def addPreBevelEdge():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        newGrp = mc.duplicate((beseMesh + '_preBaseMesh'),rr = True, un=True)
        if mc.objExists(beseMesh+'_preBaseLock'):
            mc.delete(beseMesh + '_preBaseLock')
        mc.rename(newGrp,(beseMesh + '_preBaseLock'))
        mc.hide(beseMesh + '_preBaseLock')
        mc.select(beseMesh + '_preBaseMesh')
        mel.eval("ConvertSelectionToEdges;")
        softNode = mc.polySoftEdge(angle=30)
        mc.polySelectConstraint(m=3,t=0x8000,sm=1)
        mc.polySelectConstraint(disable =True)
        hardEdges = mc.ls(sl=1,fl=1)
        bevelNodeNew = mc.polyBevel3(hardEdges, offset = 0.1, offsetAsFraction= 0, autoFit= 1, depth= 1, mitering= 1 ,miterAlong= 0 ,chamfer =1 ,segments= 3 ,worldSpace= 0 ,smoothingAngle= 30 ,subdivideNgons =1 ,mergeVertices= 1, mergeVertexTolerance= 0.0001, miteringAngle=180, angleTolerance =180 ,ch= 1)
        mc.rename(bevelNodeNew,(beseMesh+'_edgePreBevel'))
        mc.connectControl('segmentSliderPre', (beseMesh+'_edgePreBevel.segments'))
        mc.connectControl('miteringSliderPre',(beseMesh+'_edgePreBevel.mitering'))
        mc.connectControl('offsetSliderPre', (beseMesh+'_edgePreBevel.offset'))
        softHardVis()

def outlineClean():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        checkList = ['_cutterGrp','_preSubBox','_preUnionBox','_preBevelMeshUnion','_preBevelMeshSubs','_myBoolUnion','_bool','_preBaseMeshBackup' ,'_preBevelGrp','_preBaseMesh','_preBaseMeshFinal','_preBevelMeshFinal','_boolNonBevelUnion','_boolNonBevelsubs']
        for c in checkList:
            checkGrp = mc.ls((beseMesh + c), l=True)
            if len(checkGrp)>0:
                if 'BoolGrp' not in checkGrp[0]:
                    mc.parent(checkGrp[0],(beseMesh +'BoolGrp'))

def removeLeftOver():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        checkList = ['_preBevelMeshSubs','_boolNonBevelUnion','_boolNonBevelSubs','_preBevelMeshFinal']
        for c in checkList:
            if mc.objExists(beseMesh + c):
                mc.delete(beseMesh + c)

def boolPreNonBevel():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        preBevelMesh = (beseMesh + '_preBaseMesh')
        newNode = mc.duplicate(preBevelMesh,n=(beseMesh + '_preBaseMeshBackup'),rr=1,un=1)
        mc.setAttr(beseMesh + '_preBaseMeshBackup.visibility',0)
        mc.rename(newNode, (beseMesh + '_preBevel'))
        nonBevelsList = mc.textScrollList('nonBevelList', q=True, ai=True)
    
        if mc.objExists(beseMesh+'_preBevelGrp') == 0:
            newGrp = mc.duplicate((beseMesh + '_bakeStep'),rr = True, un=True)
            mc.parent(newGrp,w=True)
            mc.rename(beseMesh + '_preBevelGrp')
            mc.select(hi=True)
            #rename
            listCutters = mc.ls(sl=True, type ='transform',l=True)
            for l in listCutters:
                if '_bakeBaseMesh' in l:
                    mc.delete(l)
                else:
                    sName = l.replace('bake','pre')
                    mc.rename(l, sName.split("|")[-1])
            mc.parent((beseMesh + '_preBevelGrp'),(beseMesh + 'BoolGrp'))
            # sort operation type
        subsGrp = []
        unionGrp = []
        cutGrp = []
        for b in nonBevelsList:
            longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + b
            if mc.objExists(longName):
                checkOP = mc.getAttr(longName + '.cutterOp')
                if checkOP == 'subs':
                    subsGrp.append(b)
                elif checkOP == 'union':
                    unionGrp.append(b)
                elif checkOP == 'cut':
                    cutGrp.append(b)
    
        for s in subsGrp:
            newNode =  '|' +  beseMesh  + 'BoolGrp|' +  beseMesh  + '_preBevelGrp|'+ (s.replace('bake','pre'))
            mc.polyCBoolOp(preBevelMesh, newNode, op=2, ch=1, preserveColor=0, classification=1, name= preBevelMesh)
            mc.DeleteHistory()
            mc.rename(preBevelMesh)
        for u in unionGrp:
            newNode =  '|' +  beseMesh  + 'BoolGrp|' +  beseMesh  + '_preBevelGrp|'+ (u.replace('bake','pre'))
            mc.polyCBoolOp(preBevelMesh, newNode, op=1, ch=1, preserveColor=0, classification=1, name= preBevelMesh)
            mc.DeleteHistory()
            mc.rename(preBevelMesh)
        for c in cutGrp:
            newNode =  '|' +  beseMesh  + 'BoolGrp|' +  beseMesh  + 'BoolGrp|' + beseMesh + '_preBevelGrp|'+ (c.replace('bake','pre'))
            mc.polyCBoolOp(preBevelMesh, newNode, op=2, ch=1, preserveColor=0, classification=1, name= preBevelMesh)
            mc.DeleteHistory()
            mc.rename(preBevelMesh)
        mc.rename(beseMesh + '_preBevelMeshFinal')
        mc.parent((beseMesh + '_preBevelMeshFinal') ,( beseMesh  + 'BoolGrp|'))

def boolPreBevel():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        bevelsList = mc.textScrollList('bevelList', q=True, ai=True)
        mc.parent(('|' +  beseMesh  + 'BoolGrp|'  +  beseMesh  + '_preBevelGrp|' + beseMesh + '_preBaseMesh'),w=True)
        preBevelMesh = (beseMesh + '_preBaseMesh')
        # sort operation type
        subsGrp = []
        unionGrp = []
        cutGrp = []
        for b in bevelsList:
            longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_bakeStep|' + b
            if mc.objExists(longName):
                checkOP = mc.getAttr(longName + '.cutterOp')
                if checkOP == 'subs':
                    subsGrp.append(b)
                elif checkOP == 'union':
                    unionGrp.append(b)
                elif checkOP == 'cut':
                    cutGrp.append(b)
    
        for s in subsGrp:
            newNode =  '|' +  beseMesh  + 'BoolGrp|'  +  beseMesh  + '_preBevelGrp|'+ (s.replace('bake','pre'))
            mc.polyCBoolOp(preBevelMesh, newNode, op=2, ch=0, preserveColor=0, classification=1, name= preBevelMesh)
            mc.DeleteHistory()
            mc.rename(preBevelMesh)
        for u in unionGrp:
            newNode =  '|' +  beseMesh  + 'BoolGrp|'  +  beseMesh  + '_preBevelGrp|'+ (u.replace('bake','pre'))
            mc.polyCBoolOp(preBevelMesh, newNode, op=1, ch=0, preserveColor=0, classification=1, name= preBevelMesh)
            mc.DeleteHistory()
            mc.rename(preBevelMesh)
        for c in cutGrp:
            newNode =  '|' +  beseMesh  + 'BoolGrp|'  +  beseMesh  + '_preBevelGrp|'+ (c.replace('bake','pre'))
            mc.polyCBoolOp(preBevelMesh, newNode, op=2, ch=0, preserveColor=0, classification=1, name= preBevelMesh)
            mc.DeleteHistory()
            mc.rename(preBevelMesh)
        mc.parent(preBevelMesh,('|' +  beseMesh  + 'BoolGrp|'))
        mc.select(preBevelMesh)
        mel.eval('setSelectMode components Components')
        mc.selectType(smp= 0, sme= 1, smf= 0, smu = 0, pv= 0, pe = 1, pf= 0, puv= 0)
        mc.TogglePolyDisplayHardEdgesColor()

def setPreBevelGrp():
    bakeCutter('All')
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        newGrp = mc.duplicate((beseMesh + '_bakeStep'),rr = True, un=True)
        mc.parent(newGrp,w=True)
        mc.rename(beseMesh + '_preBevelGrp')
        mc.select(hi=True)
        #rename
        listCutters = mc.ls(sl=True, type ='transform',l=True)
        for l in listCutters:
            sName = l.replace('bake','pre')
            mc.rename(l, sName.split("|")[-1])
        #show
        listCutters = mc.ls(sl=True, type ='transform',l=True)
        for l in listCutters:
            mc.setAttr((l + '.visibility'),1)
        mc.setAttr((beseMesh + 'BoolGrp.visibility'),1)
        mc.setAttr((beseMesh + '_bakeStep.visibility'),1)
        mc.setAttr((beseMesh + '_bool.visibility'),0)
        mc.setAttr((beseMesh + '_preBevelGrp.visibility'),1)
        preCutList = mc.ls('preCutter*',type='transform')
        for i in preCutList:
            mc.setAttr((i + '.visibility'),0)
        mc.parent((beseMesh + '_preBevelGrp'),(beseMesh + 'BoolGrp'))

def sortBevelList():
    selListLeft = mc.textScrollList('bevelList', q=True, ai=True)
    if selListLeft != None:
        if len(selListLeft) > 0:
            selListLeft.sort()
            mc.textScrollList('bevelList',edit = True, ra = True)
            for s in selListLeft:
                mc.textScrollList('bevelList',edit = True, append = s)

    selListRight = mc.textScrollList('nonBevelList', q=True, ai=True)
    if selListRight != None:
        if len(selListRight) > 0:
            selListRight.sort()
            mc.textScrollList('nonBevelList',edit = True, ra = True)
            for s in selListRight:
                mc.textScrollList('nonBevelList',edit = True, append = s)



def jwSpeedCutBevelMangerSetup():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if len(beseMesh)>0:
            jwSpeedCutBevelMangerUI()
            bakeCutter('all')
            preCheckBevelByVolumn()
            loadBevelList()
            visListOn()
            mc.button('addPreBButton',e=True,en=False)
            mc.button('removePreBButton',e=True,en=False)
            mc.button('addPreNonBButton',e=True,en=False)
            mc.button('removePreNonBButton',e=True,en=False)

def softHardVis():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        checkState = mc.iconTextButton('edgeVis' , q = True , image1 = True)
        if mc.objExists((beseMesh + '_preBaseMesh')):
            mc.select(beseMesh + '_preBaseMesh')
            if checkState == 'nodeGrapherSoloed.svg':
                mc.iconTextButton('edgeVis' , e = True , image1 = 'circle.png')
                mc.TogglePolyDisplayEdges()
            else:
                mc.iconTextButton('edgeVis' , e = True , image1 = 'nodeGrapherSoloed.svg')
                mc.TogglePolyDisplayHardEdgesColor()
        #change to edge mode
        mel.eval('setSelectMode components Components')
        mc.selectType(smp= 0, sme= 1, smf= 0, smu = 0, pv= 0, pe = 1, pf= 0, puv= 0)



def jwSpeedCutBevelMangerUI():
    if mc.window("jwSpeedCutBevelManger", exists = True):
        mc.deleteUI("jwSpeedCutBevelManger")
    jwSpeedCutBevelManger = mc.window("jwSpeedCutBevelManger",title = "speedCut Bevel Manger",w = 400,h = 380, mxb = False, s = 1, bgc = [0.2, 0.2, 0.2  ])
    mc.columnLayout()
    mc.rowColumnLayout(nc= 1, cw = [(1, 420)])
    mc.separator( height=15, style='none' )
    mc.setParent( '..' )
    mc.rowColumnLayout(nc= 5, cw = [(1, 20),(2, 200),(3, 40),(4,10),(5, 200)])
    mc.text(l ='')
    mc.menuBarLayout()
    mc.rowColumnLayout(nc= 3, cw = [(1,50),(2,100),(3,20)])
    mc.text(l ='Bevel' ,en=False)
    mc.text(l ='')
    mc.iconTextButton('visLeft' , h = 20, style='iconOnly', image1 = 'nodeGrapherSoloed.svg',  c = 'togglevisLeft()')
    mc.setParent( '..' )
    mc.scrollLayout(h = 320)
    mc.textScrollList('bevelList',  h= 300, w =180, vis = True, ams= True, sc= 'selBevelList()')
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.columnLayout()
    mc.text(l ='',h=150)
    mc.iconTextButton('moveLeft' , w = 30, style='iconOnly', image1 = 'timeplay.png',  c = 'moveRightItem()')
    mc.text(l ='',h=10)
    mc.iconTextButton('moveRight' , w = 30, style='iconOnly', image1 = 'timerev.png',  c = 'moveLeftItem()')
    mc.text(l ='',h=10)
    mc.setParent( '..' )
    mc.text(l ='',h=10)
    mc.menuBarLayout()
    mc.rowColumnLayout(nc= 3, cw = [(1,50),(2,100),(3,20)])
    mc.text(l ='Ignore' ,en=False)
    mc.text(l ='')
    mc.iconTextButton('visRight' , h = 20, style='iconOnly', image1 = 'nodeGrapherSoloed.svg',  c = 'togglevisRight()')
    mc.setParent( '..' )
    mc.scrollLayout(h= 320)
    mc.textScrollList('nonBevelList',  h= 300, w =180, vis = True, ams= True, sc= 'selNonBevelList()')
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.separator( height=1, style='none' )
    mc.rowColumnLayout(nc=2, cw = [(1,215),(2,270)])
    mc.frameLayout(  labelVisible = 0,vis = 1)
    mc.columnLayout()
    mc.rowColumnLayout(nc=6, cw = [(1,55),(2,50),(3,3),(4,50),(5,3),(6,50)])
    mc.text(l ='All')
    mc.button('updatePreBButton', w = 50, l= "Auto",  c = 'preBevelUpdate()',bgc = [0.14, 0.14, 0.14] )
    mc.text(l ='')
    mc.button('killPreBButton', w = 50,   l= "x",  c = lambda *_: killPreview(),bgc = [0.14, 0.14, 0.14] )
    mc.text(l ='')
    mc.button('outMeshButton', w = 50,   l= "Output",  c = 'publishFinal()',bgc = [0.14, 0.14, 0.14] )
    mc.setParent( '..' )
    bSize = 76 #button
    sSize = 250#slider
    tSize = 65 #slider Text
    mc.separator( height=5, style='none' )
    mc.rowColumnLayout(nc=6, cw = [(1,55),(2,50),(3,3),(4,50),(5,3),(6,50)])
    mc.text(l ='Mesh ')
    mc.button('addCutButton', w = 50,   l= "Cut",  c = 'cutUpdate()',bgc = [0.14, 0.14, 0.14] )
    mc.text(l ='')
    mc.button('addLockButton', w = 50, en=0,  l= "Lock",  c = 'lcokUpdate()',bgc = [0.14, 0.14, 0.14] )
    mc.text(l ='')
    mc.button('removeLockButton', w = 50, en = 0,  l= "Remove",  c = 'bevelPreviewLockFaceRemove()',bgc = [0.14, 0.14, 0.14] )
    mc.setParent( '..' )
    mc.separator( height=5, style='none' )
    mc.rowColumnLayout(nc=4, cw = [(1,55),(2,bSize),(3,3),(4,bSize)])
    mc.text(l ='Bevel ')
    mc.button('addPreBButton', w = bSize,   l= "Add",  c = 'addPreBevelEdgeRun()',bgc = [0.14, 0.14, 0.14] )
    mc.text(l ='')
    mc.button('removePreBButton', w = bSize,   l= "Remove",  c = 'removePreBevelEdgeRun()',bgc = [0.14, 0.14, 0.14] )
    mc.setParent( '..' )
    mc.separator( height=5, style='none' )
    mc.rowColumnLayout(nc=4, cw = [(1,55),(2,bSize),(3,3),(4,bSize)])
    mc.text(l =' NonBevel')
    mc.button('addPreNonBButton', w = bSize,   l= "Add",  c = 'addNonBevelList()',bgc = [0.14, 0.14, 0.14] )
    mc.text(l ='')
    mc.button('removePreNonBButton', w = bSize,   l= "Remove",  c = 'removeNonBevelList()',bgc = [0.14, 0.14, 0.14] )
    mc.setParent( '..' )
    mc.separator( height=5, style='none' )
    mc.rowColumnLayout(nc=8, cw = [(1,55),(2,20),(3,9),(4,40),(5,3),(6,40),(7,3),(8,40)])
    mc.text(l =' Edge')
    mc.iconTextButton('edgeVis' , h = 20, style='iconOnly', image1 = 'circle.png',  c = 'softHardVis()')
    mc.text(l ='')
    mc.button('selContEdgeButton',  l= "Loop",  c = 'mc.SelectContiguousEdges()',bgc = [0.14, 0.14, 0.14] )
    mc.text(l ='')
    mc.button('edgeHardButton', l= "H",  c = 'mc.PolygonHardenEdge()',bgc = [0.14, 0.14, 0.14] )
    mc.text(l ='')
    mc.button('edgeSoftButton',  l= "S",  c = 'mc.PolygonSoftenEdge()',bgc = [0.14, 0.14, 0.14] )

    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.frameLayout(  labelVisible = 0,vis = 1)
    mc.floatSliderGrp('lockFaceSliderPre', en=1, v = 0.1, min = 0.001, max = 1, fmx = 5, s = 0.01, cw3 = [tSize,40,sSize] , label = "Lock" ,field =True)
    mc.floatSliderGrp('offsetSliderPre', en=1, v = 0.1, min = 0.001, max = 1, fmx = 10, s = 0.01, cw3 = [tSize,40,sSize] , label = "Offset" ,field =True)
    mc.intSliderGrp('segmentSliderPre',  en=1, v = 2,   min = 1 ,    max = 5, s = 1,    cw3 = [tSize,40,sSize] , label = "Segments" ,field =True)
    mc.intSliderGrp('miteringSliderPre', en=1, v = 1,   min = 0, max = 3,  s = 1, cw3 = [tSize,40,sSize] , label = "Mitering " ,field =True)
    mc.setParent( '..' )
    mc.text(l ='')
    mc.separator( height=15, style='none' )
    mc.showWindow(jwSpeedCutBevelManger)
    obNum = mc.scriptJob ( p = 'jwSpeedCutBevelManger', event = ["SelectionChanged", reselctList])
##################################################################################################################

def baseMeshColorUpdate():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        shapes = mc.listRelatives((beseMesh+'_bool'), shapes=True)
        shadeEng = mc.listConnections(shapes , type = 'shadingEngine')
        if shadeEng:
            colorData ={  2 : (0.25, 0.25 , 0.25),
                          3 : (0.6 , 0.6  , 0.6 ),
                          4 : (0.61, 0    , 0.16),
                          5 : (0.0 , 0.02 , 0.38),
                          6 : (0.0 , 0    , 1   ),
                          7 : (0.0 , 0.28 , 0.1 ),
                          8 : (0.15, 0.0  , 0.26),
                          9 : (0.78, 0.0  , 0.78),
                         10 : (0.54, 0.28 , 0.2 ),
                         11 : (0.25, 0.14 , 0.12),
                         12 : (0.32 , 0.02 , 0.0 ),
                         15 : (0.0 , 0.26 , 0.6 ),
                         20 : (1.0 , 0.43 , 0.43),
                         21 : (0.9 , 0.68 , 0.47),
                         23 : (0.0 , 0.60 , 0.33),
                         24 : (0.63, 0.42 , 0.19),
                         25 : (0.62, 0.63 , 0.19),
                         26 : (0.41, 0.63 , 0.19),
                         27 : (0.19, 0.63 , 0.36),
                         28 : (0.19, 0.63 , 0.63),
                         29 : (0.19, 0.40 , 0.63),
                         30 : (0.44, 0.15 , 0.63),
                         31 : (0.63, 0.19 , 0.42),
                         }
            score = list(colorData.items())
            materials = mc.ls(mc.listConnections(shadeEng ), materials = True)
            if mc.objExists(beseMesh+'_Shader') == 0:
                shd = mc.shadingNode('lambert', name=(beseMesh+'_Shader'), asShader=True)
                shdSG = mc.sets(name=(beseMesh+'_ShaderSG'), empty=True, renderable=True, noSurfaceShader=True)
                mc.connectAttr((shd +'.outColor'), (shdSG +'.surfaceShader'))
            colorID = random.randint(0,(len(score)-1))
            getInfo = score[colorID]
            mc.setAttr ((beseMesh +'_Shader.color'), getInfo[1][0],getInfo[1][1],getInfo[1][2], type = 'double3' )
            mc.sets((beseMesh+'_bool'), e=True, forceElement = (beseMesh+'_ShaderSG'))
            mc.setAttr((beseMesh + '_BoolResult.color'),getInfo[0])
            mc.setAttr((beseMesh + "BoolGrp.useOutlinerColor"), 1)
            mc.setAttr((beseMesh + "BoolGrp.outlinerColor"),  getInfo[1][0],getInfo[1][1],getInfo[1][2])
            mc.select(cl=1)
            outliners = mc.getPanel(type="outlinerPanel") or []
            if outliners:
                for p in outliners:
                    mc.outlinerEditor(p, edit=True, refresh=True)
            
def baseMeshColorBase():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        mc.sets((beseMesh+'_bool'), e=True, forceElement = 'initialShadingGroup')
        mc.setAttr((beseMesh + '_BoolResult.color'),0)
        mc.setAttr((beseMesh + "BoolGrp.useOutlinerColor"), 0)




def hsv2rgb(h, s, v):
    h, s, v = [float(x) for x in (h, s, v)]
    hi = (h / 60) % 6
    hi = int(round(hi))
    f = (h / 60) - (h / 60)
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    if hi == 0:
        return v, t, p
    elif hi == 1:
        return q, v, p
    elif hi == 2:
        return p, v, t
    elif hi == 3:
        return p, q, v
    elif hi == 4:
        return t, p, v
    elif hi == 5:
        return v, p, q

def toggleLayer():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        BoolGrpList = mc.ls('*BoolGrp')
        activeGroups = [g for g in BoolGrpList if mc.objExists(g + ".active") and mc.getAttr(g + ".active") == 1]
        checkState = mc.iconTextButton('meshLayerButton', q=1, image1= True )
        if checkState == 'nodeGrapherModeSimple.svg':
            mc.iconTextButton('meshLayerButton', e=1, image1= 'nodeGrapherModeAll.svg')
            mc.showHidden(activeGroups)
        else:
            mc.iconTextButton('meshLayerButton', e=1, image1= 'nodeGrapherModeSimple.svg')
            mc.hide(activeGroups)
            mc.showHidden(beseMesh+'BoolGrp')

def updateVisLayer():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        BoolGrpList = mc.ls('*BoolGrp')
        activeGroups = [g for g in BoolGrpList if mc.objExists(g + ".active") and mc.getAttr(g + ".active") == 1]
        checkState = mc.iconTextButton('meshLayerButton', q=1, image1= True )
        if checkState == 'nodeGrapherModeSimple.svg':
            mc.hide(activeGroups)
            mc.showHidden(beseMesh+'BoolGrp')
        else:
            mc.showHidden(activeGroups)

def cutterType(boolType):
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        checkButtonStateList = ['subsButton','unionButton','cutButton']
        for c in checkButtonStateList:
            buttonState = mc.button( c ,e=1,  bgc = [0.28,0.28,0.28] )
        selCutter = mc.ls(sl=1, fl=1, type='transform')
        if len(selCutter) > 0:
            selCutterCheck = mc.ls(sl=1, fl=1, l=1, type='transform')
            for s in selCutterCheck:
                checkShortName = s.split("|")
                shortName = checkShortName[-1]
                mc.select(s)
                myType = checkInstType()
                if myType[1] != 'new':
                    s = myType[0]
    
                if 'boxCutter' in shortName:
                    mc.setAttr((s+'.cutterOp'),boolType,type="string")
                    shapeNode = mc.listRelatives(s, f = True, shapes=True)
                    if boolType == 'union':
                        mc.setAttr( (shapeNode[0]+'.overrideColor'), 31)
                    elif boolType == 'subs':
                        mc.setAttr( (shapeNode[0]+'.overrideColor'), 28)
                    elif boolType == 'cut':
                        mc.setAttr( (shapeNode[0]+'.overrideColor'), 25)
                    fixBoolNodeConnection()
    
        if boolType == 'union':
            buttonState = mc.button('unionButton',e=1,  bgc = [0.3,0.5,0.6] )
        elif boolType == 'subs':
            buttonState = mc.button('subsButton' ,e=1,  bgc = [0.3,0.5,0.6] )
        elif boolType == 'cut':
            buttonState = mc.button('cutButton' ,e=1,  bgc = [0.3,0.5,0.6] )

def fixBoolNodeConnection():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        transNode = mc.ls(sl=1,fl=1)
        myType = checkInstType()
        if myType[1] != 'new':
            transNode[0] = myType[0]
    
        checkNumber = ''.join([n for n in transNode[0].split('|')[-1] if n.isdigit()])
        opType = mc.getAttr(transNode[0]+'.cutterOp')
        shapeNode = mc.listRelatives(transNode[0], s=True ,f=True)
        boolNode = ''
    
        if 'subs' in opType:
            boolNode = beseMesh+'_mySubs'
        elif 'union' in opType:
            boolNode = beseMesh+'_myUnion'
        elif 'cut' in opType:
            boolNode = beseMesh+'_myCut'
    
        if len(shapeNode)>0:
            listConnect = mc.connectionInfo((shapeNode[0]+'.outMesh'), dfs=True )
            if len(listConnect)>0:
                for a in listConnect:
                    mc.disconnectAttr((shapeNode[0]+'.outMesh'), a)
    
    
        start_index = 0
        while start_index < 1000:
            listConnectMa = mc.connectionInfo((shapeNode[0]+'.worldMatrix[' + str(start_index) + ']'), dfs=True )
            if len(listConnectMa) > 0:
                for a in listConnectMa:
                    try:
                        mc.disconnectAttr((shapeNode[0]+'.worldMatrix[' + str(start_index) + ']'), a)
                    except:
                        pass
            start_index += 1
    
        if mc.objExists(boolNode) == 0:#fixing breaking bool node and link
            bakeCutter("all")
            
        mc.connectAttr( (shapeNode[0]+".outMesh"), ((boolNode+'.inputPoly['+str(checkNumber)+']')),f=True)
        mc.connectAttr( (shapeNode[0]+".worldMatrix[0]"), ((boolNode+'.inputMat['+str(checkNumber)+']')),f=True)
    
        if myType[1] != 'new':
            mc.select(transNode[0]+'*Grp')
            grpName = mc.ls(sl=True,fl=True)
            transformList = mc.listRelatives(grpName, c=True)
            cleanList = []
            if  myType[1] == 'radial':
                for t in transformList:
                    removeUnwant = t.replace('_Rot','')
                    cleanList.append(removeUnwant)
            else:
                cleanList = transformList
            cleanList.remove(transNode[0])
            for i in range(len(cleanList)):
                checkNumber = ''.join([n for n in cleanList[i].split('|')[-1] if n.isdigit()])
                mc.connectAttr( (shapeNode[0]+".worldMatrix[" + str(int(i)+ int(1)) + "]"), ((boolNode+'.inputMat['+str(checkNumber)+']')),f=True)
                mc.connectAttr( (shapeNode[0]+".outMesh"), ((boolNode+'.inputPoly['+str(checkNumber)+']')),f=True)

def get_latest_free_multi_index( attr_name, start_index ):
    '''Find the latest unconnected multi index starting at the passed in index.'''
    listCuttersIndex = []
    while start_index < MAX_BOOL_CONNECTIONS:
        if mc.connectionInfo( '{}[{}]'.format(attr_name,start_index), sfd=True ):
            listCuttersIndex.append(start_index)
        start_index += 1
    nextIndex = (listCuttersIndex[-1]+1)
    return nextIndex


def nextCutterNumber():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        cutterGrpName = beseMesh + '_cutterGrp'
        mc.select(cutterGrpName,hi=True)
        listAllCutter = mc.ls('boxCutter*',type = 'transform')
        mc.select(cl=True)
        checkNumber = 2
        if len(listAllCutter) > 0:
            newList = []
            for l in listAllCutter:
                if 'ArrayGrp' not in l:
                    newList.append(l)
                else:
                    grpNumber = ''.join([n for n in l.split('|')[-1] if n.isdigit()])
                    newList.append(grpNumber)
            checkNumber = ''.join([n for n in newList[-1].split('|')[-1] if n.isdigit()])
            checkNumber = int(checkNumber) + 1
        return checkNumber

def get_next_free_multi_index( attr_name, start_index ):
    '''Find the next unconnected multi index starting at the passed in index.'''
    # assume a max of 100 connections
    while start_index < MAX_BOOL_CONNECTIONS:
        if len( mc.connectionInfo( '{}[{}]'.format(attr_name,start_index), sfd=True ) or [] ) == 0:
            return start_index
        start_index += 1
    return 0

#################################################################################################
def goDraw():
    hideAllCutter()
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    snapMesh = beseMesh + '_bool'
    mc.optionVar(iv = ('inViewMessageEnable', 0))
    mc.makeLive(snapMesh)
    xrayOn()
    mc.evalDeferred('drawBoxRun()')


def drawBoxRun():
    mc.setToolTo( "CreatePolyCubeCtx" )
    mc.scriptJob ( runOnce=True, event = ["PostToolChanged", xrayOff])


def xrayOn():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        snapMesh = beseMesh + '_bool'
        mc.displaySurface(snapMesh , x =1)

def xrayOff():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        snapMesh = beseMesh + '_bool'
        mc.displaySurface(snapMesh , x =0)
        mc.makeLive( none=True )
        newCut = mc.ls(sl=1,tr=1)
        mc.select(newCut, r=1)
        mc.evalDeferred('useOwnCutterShape()')
        newCut = mc.ls(sl=1,tr=1)
        mc.setAttr((newCut[0]+".scaleX") ,1.01)
        mc.setAttr((newCut[0]+".scaleY") ,1.01)
        mc.setAttr((newCut[0]+".scaleZ") ,1.01)

#####################################################################################################

def rdMirrorCurrentState():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        rdMAxis = ''
        rdMPol = ''
        divSide = 3
        divOffset = 10
        bcv = mc.button('rMirrorXButton',q=1, bgc =1)
        totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
        if totalBcVX < 0.27:
            rdMAxis = 'x'
        bcv = mc.button('rMirrorYButton',q=1, bgc =1)
        totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
        if totalBcVX < 0.27:
            rdMAxis = 'y'
        bcv = mc.button('rMirrorZButton',q=1, bgc =1)
        totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
        if totalBcVX < 0.27:
            rdMAxis = 'z'
        checkV = mc.button('rMirrorPosButton', q=1 , bgc = 1)
        if checkV[0] > 0.30 :
            rdMPol = 'p'
        checkV = mc.button('rMirrorNegButton', q=1 , bgc = 1)
        if checkV[0] > 0.30 :
            rdMPol = 'n'
        divSide = mc.intSliderGrp('rMirrorSideSlider',  q=1 , v = 1)
        divOffset = mc.intSliderGrp('rMirrorOffsetSlider',  q=1 , v = 1)
        return rdMAxis, rdMPol, divSide, divOffset

def rdMirrorUIUpdate():
    answer = ['','','','']
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if mc.objExists((beseMesh + "_rMirrorGrp")):
        answer[0]= mc.getAttr(beseMesh + '_rMirrorGrp.rdMAxis')
        answer[1]= mc.getAttr(beseMesh + '_rMirrorGrp.rdMHalf')
        answer[2]= mc.getAttr(beseMesh + '_rMirrorGrp.rdMSide')
        answer[3]= mc.getAttr(beseMesh + '_rMirrorGrp.rdMOffset')
        rdMirrorReset()
        if answer[0] == 'x':
            mc.button('rMirrorXButton',e=1, bgc =  [0.34, 0.14, 0.14])
        elif answer[0] == 'y':
            mc.button('rMirrorYButton',e=1, bgc =  [0.14, 0.34, 0.14])
        elif answer[0] == 'z':
            mc.button('rMirrorZButton',e=1, bgc =  [0.14, 0.14, 0.34])
        if answer[1] == 'p':
            mc.button('rMirrorPosButton', e=1 , bgc = [0.3, 0.5, 0.6])
        elif answer[1] == 'n':
            mc.button('rMirrorNegButton', e=1 , bgc = [0.3, 0.5, 0.6])
        mc.intSliderGrp('rMirrorSideSlider',  e=1 , v = answer[2] )
        mc.intSliderGrp('rMirrorOffsetSlider',  e=1 , v = answer[3] )
    else:
        rdMirrorReset()

def rdMirrorReset():
    mc.button('rMirrorXButton',e=1, bgc = [0.28,0.28,0.28])
    mc.button('rMirrorYButton',e=1, bgc = [0.28,0.28,0.28])
    mc.button('rMirrorZButton',e=1, bgc = [0.28,0.28,0.28])
    mc.button('rMirrorNegButton', e=1 , bgc = [0.28,0.28,0.28])
    mc.button('rMirrorPosButton', e=1 , bgc = [0.28,0.28,0.28])
    mc.intSliderGrp('rMirrorSideSlider',  e=1 , v = 3)

def rdMirrorOffsetUpdate():
    rMirrorList = mc.ls('*_rMirrorGrp')
    offsetV = mc.intSliderGrp('rMirrorOffsetSlider',q=1,v=1)
    for r in rMirrorList:
        mc.move((-1.0*offsetV), 0, 0 ,r , a=1, os=1, wd=1)
        mc.setAttr((r + '.rdMOffset'),offsetV)

def rdMirrorOutput():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if mc.objExists((beseMesh + "_rMirrorGrp")):
        insList = mc.ls((beseMesh + "_ringGrp*"),fl=1)
        mc.select(beseMesh + "_ringGrp")
        collectList = []
        for i in insList:
            new = mc.duplicate((beseMesh + "_ringGrp"),rr=1)
            collectList.append(new)
            mc.select(new,i)
            mc.matchTransform(pos=1,rot=1)
        mc.delete(insList)
        mc.select(beseMesh + "_rMirrorGrp")
        mc.polyUnite(ch=0, objectPivot=1)
        mc.rename(beseMesh + "_rMirrorGeo")
        mc.delete(beseMesh + "_rMirrorGrp")
        mc.polyMergeVertex(d=MERGE_VERTEX_TOLERANCE, am=1, ch=0)
        mc.select(beseMesh + "_rMirrorGeo")
        mc.button('rMirrorPosButton', e=1 ,bgc = [0.28,0.28,0.28])
        mc.button('rMirrorNegButton', e=1 ,bgc = [0.28,0.28,0.28])
        mc.button('rMirrorXButton',e=1, bgc = [0.28,0.28,0.28])
        mc.button('rMirrorYButton',e=1, bgc = [0.28,0.28,0.28])
        mc.button('rMirrorZButton',e=1, bgc = [0.28,0.28,0.28])
        mc.intSliderGrp('rMirrorSideSlider',  e=1 , v = 3)

def rdMirrorHalf(side):
    buttonXOn = 1
    buttonYOn = 1
    buttonZOn = 1
    bcv = mc.button('rMirrorXButton',q=1, bgc =1)
    totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
    if totalBcVX > 0.27:
        buttonXOn = 0

    bcv = mc.button('rMirrorYButton',q=1, bgc =1)
    totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
    if totalBcVX > 0.27:
        buttonYOn = 0

    bcv = mc.button('rMirrorZButton',q=1, bgc =1)
    totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
    if totalBcVX > 0.27:
        buttonZOn = 0
    if buttonXOn == 0 and buttonYOn == 0 and buttonZOn == 0:
        if mc.objExists((beseMesh + "_rMirrorGrp")):
            mc.delete((beseMesh + "_rMirrorGrp"))
    else:
        if side == 'p':
            checkV = mc.button('rMirrorPosButton', q=1 , bgc = 1)
            if checkV[0] < 0.30 :
                mc.button('rMirrorPosButton', e=1 , bgc = [0.3, 0.5, 0.6])
            else:
                mc.button('rMirrorPosButton', e=1 , bgc = [0.28,0.28,0.28])
            mc.button('rMirrorNegButton', e=1 , bgc = [0.28,0.28,0.28])
        elif side == 'n':
            checkV = mc.button('rMirrorNegButton', q=1 , bgc = 1)
            if checkV[0] < 0.30 :
                mc.button('rMirrorNegButton', e=1 , bgc = [0.3, 0.5, 0.6])
            else:
                mc.button('rMirrorNegButton', e=1 , bgc = [0.28,0.28,0.28])
            mc.button('rMirrorPosButton', e=1 , bgc = [0.28,0.28,0.28])
        rdMirrorUpdate()

def rdMirror(axis):
    currentSel = mc.ls(sl=1)
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if len(beseMesh) > 0:
            divSide =  mc.intSliderGrp('rMirrorSideSlider',  q=1 , v = 1)
            divAngle = 360.0 /  divSide
            commnadA = ''
            commnadC = ''
            commnadD = ''
            commnadG = ''
            rotV = 90 - (360.0 / divSide / 2)
            createMirror = 1
            halfOn = 0
            checkVP = mc.button('rMirrorPosButton', q=1 , bgc = 1)
            checkVN = mc.button('rMirrorNegButton', q=1 , bgc = 1)
            if (checkVP[1]+ checkVN[1]) > 0.57:
                halfOn = 1
    
            buttonXOn = 1
            buttonYOn = 1
            buttonZOn = 1
            bcv = mc.button('rMirrorXButton',q=1, bgc =1)
            totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
            if totalBcVX > 0.27:
                buttonXOn = 0
    
            bcv = mc.button('rMirrorYButton',q=1, bgc =1)
            totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
            if totalBcVX > 0.27:
                buttonYOn = 0
    
            bcv = mc.button('rMirrorZButton',q=1, bgc =1)
            totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
            if totalBcVX > 0.27:
                buttonZOn = 0
            if buttonXOn == 0 and buttonYOn == 0 and buttonZOn == 0:
                if mc.objExists((beseMesh + "_rMirrorGrp")):
                    mc.delete((beseMesh + "_rMirrorGrp"))
    
            if axis == 'x':
                if buttonXOn == 1:
                    if mc.objExists((beseMesh + "_rMirrorGrp")):
                        mc.delete((beseMesh + "_rMirrorGrp"))
                    mc.button('rMirrorXButton',e=1, bgc = [0.28,0.28,0.28])
                    createMirror = 0
                else:
                    if buttonYOn == 1 or buttonZOn == 1:
                        if mc.objExists((beseMesh + "_rMirrorGrp")):
                            mc.delete((beseMesh + "_rMirrorGrp"))
                    commnadA = 'polyMirrorCut 0.001 0 1;'
                    commnadC = 'rotate -r  ' + str(divAngle) +  ' 0 0;'
    
                    if halfOn == 1:
                        if checkVP[1] > 0.30:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(90) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(rotV) + ');'
                        else:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(rotV) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(90) + ');'
    
                    else:
                        commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(rotV) + ');'
                        commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(rotV) + ');'
                    mc.button('rMirrorXButton',e=1, bgc = [0.34, 0.14, 0.14])
                    mc.button('rMirrorYButton',e=1, bgc = [0.28,0.28,0.28])
                    mc.button('rMirrorZButton',e=1, bgc = [0.28,0.28,0.28])
    
            elif axis == 'y':
                if buttonYOn == 1:
                    if mc.objExists((beseMesh + "_rMirrorGrp")):
                        mc.delete((beseMesh + "_rMirrorGrp"))
                    mc.button('rMirrorYButton',e=1, bgc = [0.28,0.28,0.28])
                    createMirror = 0
                else:
                    if buttonXOn == 1 or buttonZOn == 1:
                        if mc.objExists((beseMesh + "_rMirrorGrp")):
                            mc.delete((beseMesh + "_rMirrorGrp"))
                    commnadA = 'polyMirrorCut 0 0.001 1;'
                    commnadC = 'rotate -r  0 ' + str(divAngle) +  ' 0;'
                    if halfOn == 1:
                        if checkVP[1] > 0.30:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateY (' + str(90) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateY (-1.0 * ' + str(rotV) + ');'
                        else:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateY (' + str(rotV) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateY (-1.0 * ' + str(90) + ');'
                    else:
                        commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateY (' + str(rotV) + ');'
                        commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateY (-1.0 * ' + str(rotV) + ');'
                    mc.button('rMirrorXButton',e=1, bgc = [0.28,0.28,0.28])
                    mc.button('rMirrorYButton',e=1, bgc = [0.14, 0.34, 0.14])
                    mc.button('rMirrorZButton',e=1, bgc = [0.28,0.28,0.28])
            else:
                if buttonZOn == 1:
                    if mc.objExists((beseMesh + "_rMirrorGrp")):
                        mc.delete((beseMesh + "_rMirrorGrp"))
                    mc.button('rMirrorZButton',e=1, bgc = [0.28,0.28,0.28])
                    createMirror = 0
                else:
                    if buttonXOn == 1 or buttonYOn == 1:
                        if mc.objExists((beseMesh + "_rMirrorGrp")):
                            mc.delete((beseMesh + "_rMirrorGrp"))
    
                    commnadA = 'polyMirrorCut 1 0 0.001;'
                    commnadC = 'rotate -r 0 0 ' + str(divAngle) +  ';'
    
                    if halfOn == 1:
    
                        if checkVP[1] > 0.30:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(90) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(rotV) + ');'
                        else:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(rotV) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(90) + ');'
                    else:
                        commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(rotV) + ');'
                        commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(rotV) + ');'
                    mc.button('rMirrorXButton',e=1, bgc = [0.28,0.28,0.28])
                    mc.button('rMirrorYButton',e=1, bgc = [0.28,0.28,0.28])
                    mc.button('rMirrorZButton',e=1, bgc = [0.14, 0.14, 0.34])
    
            if createMirror == 1:
                rmSource = beseMesh+ '_bool'
                newRing = mc.duplicate(rmSource)
                mc.rename(newRing , (beseMesh + '_ringGeo'))
                mc.connectAttr( (rmSource+'Shape.outMesh') ,(beseMesh + '_ringGeoShape.inMesh'),f=1)
                mc.select(beseMesh + '_ringGeo')
                mel.eval(commnadA)
                mc.rename(beseMesh + '_cutPlaneA')
                mc.select((beseMesh + '_ringGeo'),add=1)
                mc.matchTransform(pos=1)
                connList = mc.listConnections((beseMesh + '_cutPlaneA'),t= "transform")
                mc.delete(connList[0])
                mel.eval(commnadD)
                mc.select(beseMesh + '_ringGeo')
                mel.eval(commnadA)
                mc.rename(beseMesh + '_cutPlaneB')
                mc.select((beseMesh + '_ringGeo'),add=1)
                mc.matchTransform(pos=1)
                mel.eval(commnadG)
                connListB = mc.listConnections((beseMesh + '_cutPlaneB'),t= "transform")
    
                if halfOn == 1:
                    mc.rename(connListB[0], (beseMesh + '_ringGeoMirror'))
                    mc.group((beseMesh + '_ringGeo'),(beseMesh + '_ringGeoMirror'))
                else:
                    mc.delete(connListB[0])
                    mc.group((beseMesh + '_ringGeo'))
                mc.rename(beseMesh + '_ringGrp')
                getTrans = mc.xform((beseMesh + '_cutPlaneA'), q=1, piv=1, a=1, ws=1)
                mc.move(getTrans[0], getTrans[1], getTrans[2],(beseMesh + '_ringGrp.scalePivot'), (beseMesh + '_ringGrp.rotatePivot'), a=1, ws=1)
                mc.instance()
                mel.eval(commnadC)
                for i in range(divSide-2):
                    mc.instance(st=1)
                mc.group((beseMesh + '_cutPlane*'),(beseMesh + '_ringGrp*'))
                mc.rename(beseMesh + "_rMirrorGrp")
                offsetV = mc.intSliderGrp('rMirrorOffsetSlider',q=1,v=1)
                mc.move((-1.0*offsetV), 0, 0 ,r=1, os=1, wd=1)
                mc.setAttr((beseMesh + '_cutPlaneA.visibility'),0)
                mc.setAttr((beseMesh + '_cutPlaneB.visibility'),0)
                mc.parent((beseMesh + "_rMirrorGrp"),(beseMesh + "BoolGrp"))
                mc.select(d=1)
                if not mc.attributeQuery('rdMAxis', node = (beseMesh + '_rMirrorGrp'), ex=True ):
                    mc.addAttr((beseMesh + '_rMirrorGrp'), ln='rdMAxis' ,dt= 'string')
                if not mc.attributeQuery('rdMHalf', node = (beseMesh + '_rMirrorGrp'), ex=True ):
                    mc.addAttr((beseMesh + '_rMirrorGrp'), ln='rdMHalf' ,dt= 'string')
                if not mc.attributeQuery('rdMSide', node = (beseMesh + '_rMirrorGrp'), ex=True ):
                    mc.addAttr((beseMesh + '_rMirrorGrp'),at='long' , dv = 0 ,ln='rdMSide')
                if not mc.attributeQuery('rdMOffset', node = (beseMesh + '_rMirrorGrp'), ex=True ):
                    mc.addAttr((beseMesh + '_rMirrorGrp'),at='long' , dv = 0 ,ln='rdMOffset')
                answer = rdMirrorCurrentState()
                mc.setAttr((beseMesh + '_rMirrorGrp.rdMAxis'), answer[0], type="string")
                mc.setAttr((beseMesh + '_rMirrorGrp.rdMHalf'), answer[1], type="string")
                mc.setAttr((beseMesh + '_rMirrorGrp.rdMSide'), answer[2])
                mc.setAttr((beseMesh + '_rMirrorGrp.rdMOffset'), answer[3])
            else:
                rdMirrorReset()
            if currentSel:
                mc.select(currentSel)
                mc.MoveTool()

def rdMirrorUpdate():
    currentSel = mc.ls(sl=1)
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if len(beseMesh) > 0:
            if mc.objExists((beseMesh + "_rMirrorGrp")):
                divSide =  mc.intSliderGrp('rMirrorSideSlider',  q=1 , v = 1)
                divAngle = 360.0 /  divSide
                commnadA = ''
                commnadC = ''
                commnadD = ''
                commnadG = ''
                rotV = 90 - (360.0 / divSide / 2)
                createMirror = 1
                halfOn = 0
                checkVP = mc.button('rMirrorPosButton', q=1 , bgc = 1)
                checkVN = mc.button('rMirrorNegButton', q=1 , bgc = 1)
                if (checkVP[1]+ checkVN[1]) > 0.57:
                    halfOn = 1
                buttonXOn = 1
                buttonYOn = 1
                buttonZOn = 1
                bcv = mc.button('rMirrorXButton',q=1, bgc =1)
                totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
                if totalBcVX > 0.27:
                    buttonXOn = 0
                bcv = mc.button('rMirrorYButton',q=1, bgc =1)
                totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
                if totalBcVX > 0.27:
                    buttonYOn = 0
                bcv = mc.button('rMirrorZButton',q=1, bgc =1)
                totalBcVX = (bcv[0]+ bcv[1]+ bcv[2])/3
                if totalBcVX > 0.27:
                    buttonZOn = 0
                if buttonXOn == 1 or buttonYOn == 1 or buttonZOn == 1:
                    if mc.objExists((beseMesh + "_rMirrorGrp")):
                        mc.delete((beseMesh + "_rMirrorGrp"))
                if buttonXOn == 1:
                    commnadA = 'polyMirrorCut 0.001 0 1;'
                    commnadC = 'rotate -r  ' + str(divAngle) +  ' 0 0;'
                    if halfOn == 1:
                        if checkVP[1] > 0.30:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(90) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(rotV) + ');'
                        else:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(rotV) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(90) + ');'
                    else:
                        commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(rotV) + ');'
                        commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(rotV) + ');'
                elif buttonYOn == 1:
                    commnadA = 'polyMirrorCut 0 0.001 1;'
                    commnadC = 'rotate -r  0 ' + str(divAngle) +  ' 0;'
                    if halfOn == 1:
                        if checkVP[1] > 0.30:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateY (' + str(90) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateY (-1.0 * ' + str(rotV) + ');'
                        else:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateY (' + str(rotV) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateY (-1.0 * ' + str(90) + ');'
                    else:
                        commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateY (' + str(rotV) + ');'
                        commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateY (-1.0 * ' + str(rotV) + ');'
    
                elif buttonZOn == 1:
                    commnadA = 'polyMirrorCut 1 0 0.001;'
                    commnadC = 'rotate -r 0 0 ' + str(divAngle) +  ';'
                    if halfOn == 1:
                        if checkVP[1] > 0.30:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(90) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(rotV) + ');'
                        else:
                            commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(rotV) + ');'
                            commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(90) + ');'
                    else:
                        commnadD = 'setAttr '  + beseMesh + '_cutPlaneA.rotateX (-1.0 * ' + str(rotV) + ');'
                        commnadG = 'setAttr '  + beseMesh + '_cutPlaneB.rotateX (' + str(rotV) + ');'
    
    
                if createMirror == 1:
                    rmSource = beseMesh+ '_bool'
                    newRing = mc.duplicate(rmSource)
                    mc.rename(newRing , (beseMesh + '_ringGeo'))
                    mc.connectAttr( (rmSource+'Shape.outMesh') ,(beseMesh + '_ringGeoShape.inMesh'),f=1)
                    mc.select(beseMesh + '_ringGeo')
                    mel.eval(commnadA)
                    mc.rename(beseMesh + '_cutPlaneA')
                    mc.select((beseMesh + '_ringGeo'),add=1)
                    mc.matchTransform(pos=1)
                    connListA = mc.listConnections((beseMesh + '_cutPlaneA'),t= "transform")
                    mc.delete(connListA[0])
                    mel.eval(commnadD)
                    mc.select(beseMesh + '_ringGeo')
                    mel.eval(commnadA)
                    mc.rename(beseMesh + '_cutPlaneB')
                    mc.select((beseMesh + '_ringGeo'),add=1)
                    mc.matchTransform(pos=1)
                    mel.eval(commnadG)
                    connListB = mc.listConnections((beseMesh + '_cutPlaneB'),t= "transform")
    
                    if halfOn == 1:
                        mc.rename(connListB[0], (beseMesh + '_ringGeoMirror'))
                        mc.group((beseMesh + '_ringGeo'),(beseMesh + '_ringGeoMirror'))
                    else:
                        mc.delete(connListB[0])
                        mc.group((beseMesh + '_ringGeo'))
                    mc.rename(beseMesh + '_ringGrp')
                    getTrans = mc.xform((beseMesh + '_cutPlaneA'), q=1, piv=1, a=1, ws=1)
                    mc.move(getTrans[0], getTrans[1], getTrans[2],(beseMesh + '_ringGrp.scalePivot'), (beseMesh + '_ringGrp.rotatePivot'), a=1, ws=1)
                    mc.instance()
                    mel.eval(commnadC)
                    for i in range(divSide-2):
                        mc.instance(st=1)
                    mc.group((beseMesh + '_cutPlane*'),(beseMesh + '_ringGrp*'))
                    mc.rename(beseMesh + "_rMirrorGrp")
                    offsetV = mc.intSliderGrp('rMirrorOffsetSlider',q=1,v=1)
                    mc.move((-1.0*offsetV), 0, 0 ,r=1, os=1, wd=1)
                    mc.setAttr((beseMesh + '_cutPlaneA.visibility'),0)
                    mc.setAttr((beseMesh + '_cutPlaneB.visibility'),0)
                    mc.parent((beseMesh + "_rMirrorGrp"),(beseMesh + "BoolGrp"))
                    mc.select(d=1)
                    if not mc.attributeQuery('rdMAxis', node = (beseMesh + '_rMirrorGrp'), ex=True ):
                        mc.addAttr((beseMesh + '_rMirrorGrp'), ln='rdMAxis' ,dt= 'string')
                    if not mc.attributeQuery('rdMHalf', node = (beseMesh + '_rMirrorGrp'), ex=True ):
                        mc.addAttr((beseMesh + '_rMirrorGrp'), ln='rdMHalf' ,dt= 'string')
                    if not mc.attributeQuery('rdMSide', node = (beseMesh + '_rMirrorGrp'), ex=True ):
                        mc.addAttr((beseMesh + '_rMirrorGrp'),at='long' , dv = 0 ,ln='rdMSide')
                    if not mc.attributeQuery('rdMOffset', node = (beseMesh + '_rMirrorGrp'), ex=True ):
                        mc.addAttr((beseMesh + '_rMirrorGrp'),at='long' , dv = 0 ,ln='rdMOffset')
                    answer = rdMirrorCurrentState()
                    mc.setAttr((beseMesh + '_rMirrorGrp.rdMAxis'), answer[0], type="string")
                    mc.setAttr((beseMesh + '_rMirrorGrp.rdMHalf'), answer[1], type="string")
                    mc.setAttr((beseMesh + '_rMirrorGrp.rdMSide'), answer[2])
                    mc.setAttr((beseMesh + '_rMirrorGrp.rdMOffset'), answer[3])
                else:
                    rdMirrorReset()
    
                if currentSel:
                    mc.select(currentSel)
                    mc.MoveTool()

#####################################################################################################
def symmetryCutter():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        getSymX = 0
        getSymY = 0
        getSymZ = 0
    
        mc.setAttr((beseMesh+'.visibility'), 1)
        mirrorPivot = mc.objectCenter(beseMesh, gl=True)
        mc.setAttr((beseMesh+'.visibility'), 0)
    
        if mc.attributeQuery('symmetryX', node = beseMesh, ex=True ):
            getSymX =  mc.getAttr(beseMesh+'.symmetryX')
        if mc.attributeQuery('symmetryY', node = beseMesh, ex=True ):
            getSymY =  mc.getAttr(beseMesh+'.symmetryY')
        if mc.attributeQuery('symmetryZ', node = beseMesh, ex=True ):
            getSymZ =  mc.getAttr(beseMesh+'.symmetryZ')
    
        if getSymX != 0 or getSymY != 0 or getSymZ != 0:
            #mirror all cutter
            mc.select((beseMesh+'_bakeStep'), hi=True)
            mc.select((beseMesh+'_bakeStep'),d=True)
            mc.select((beseMesh+'_bakeBaseMesh'),d=True)
            restoreCutter = mc.ls(sl=1,fl=1,type='transform')
            for r in restoreCutter:
                if getSymX == 1:
                    mc.polyMirrorFace(r, cutMesh = 1, axis = 0 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1,  ws =1, p = mirrorPivot)
                elif  getSymX == -1:
                    mc.polyMirrorFace(r, cutMesh = 1, axis = 0 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =1, p = mirrorPivot)
    
                if getSymY == 1:
                    mc.polyMirrorFace(r, cutMesh = 1, axis = 1 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1,  ws =1, p = mirrorPivot)
                elif  getSymY == -1:
                    mc.polyMirrorFace(r, cutMesh = 1, axis = 1 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =1, p = mirrorPivot)
    
                if getSymZ == 1:
                    mc.polyMirrorFace(r, cutMesh = 1, axis = 2 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1,  ws =1, p = mirrorPivot)
                elif  getSymZ == -1:
                    mc.polyMirrorFace(r, cutMesh = 1, axis = 2 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1,  ws =1, p = mirrorPivot)

def fadeOutCage():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if mc.objExists(beseMesh+'_cageGrp'):
            mc.setAttr((beseMesh+'_cageGrp.visibility'),1)
            storeCurrent = mc.floatSlider('CageTransparentSlider',q=1 ,value=True)
            val = storeCurrent
            i = 0.005
            while val < 1:
                i += 0.005
                val = 0.5 + i
                mc.setAttr("CageShader.transparencyB", val)
                mc.setAttr("CageShader.transparencyR", val)
                mc.setAttr("CageShader.transparencyG", val)
                mc.refresh(cv=True,f=True)
    
            mc.setAttr((beseMesh+'_cageGrp.visibility'),0)
            mc.setAttr("CageShader.transparencyB", storeCurrent)
            mc.setAttr("CageShader.transparencyR", storeCurrent)
            mc.setAttr("CageShader.transparencyG", storeCurrent)

def updateCageColor():
    if mc.objExists('CageShader'):
        checkColor = mc.colorSliderGrp('CageColorSlider', q=True, rgb=True )
        mc.setAttr('CageShader.color', checkColor[0], checkColor[1], checkColor[2] , type= 'double3')

def updateCageTransparent():
    if mc.objExists('CageShader'):
        checkTransp = 0
        checkTransp = mc.floatSlider('CageTransparentSlider',q=True, value=True)
        mc.setAttr('CageShader.transparency', checkTransp, checkTransp, checkTransp, type= 'double3')

def cageVisToggle():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        listAllCageGrps = mc.ls('*_cageGrp')
        if mc.objExists(beseMesh+'_cageGrp'):
            checkState = mc.getAttr(beseMesh+'_cageGrp.visibility')
            mc.hide(listAllCageGrps)
            if checkState == 0:
                mc.setAttr((beseMesh+'_cageGrp.visibility'),1)
            else:
                mc.setAttr((beseMesh+'_cageGrp.visibility'),0)
        else:
            mc.hide(listAllCageGrps)

def boolSymmetryCage():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if mc.objExists(beseMesh +'_cageGrp'):
            mc.delete(beseMesh +'_cageGrp')
        if mc.objExists(beseMesh +'_cageA*'):
            mc.delete(beseMesh +'_cageA*')
        tempLattice = mc.lattice(beseMesh,divisions =(2, 2, 2), objectCentered = True, ldv = (2, 2 ,2))
        BBcenter = mc.xform(tempLattice[1],q =True, t=True)
        BBrotate = mc.xform(tempLattice[1],q =True, ro=True)
        BBscale  = mc.xform(tempLattice[1],q =True, r=True, s=True)
        BBcube = mc.polyCube(w =1, h =1, d =1, sx= 1, sy= 1, sz= 1, ax= (0, 1, 0), ch = 0)
        mc.xform(BBcube[0], t = (BBcenter[0], BBcenter[1],BBcenter[2]))
        mc.xform(BBcube[0], ro = (BBrotate[0], BBrotate[1],BBrotate[2]))
        mc.xform(BBcube[0], s = (BBscale[0], BBscale[1],BBscale[2]))
        mc.delete(tempLattice)
        mc.rename(BBcube[0],(beseMesh+'_cageA'))
        mc.setAttr((beseMesh+'.visibility'), 1)
        mirrorPivot = mc.objectCenter(beseMesh, gl=True)
        mc.setAttr((beseMesh+'.visibility'), 0)
        cutDir = {'X','Y','Z'}
        for c in cutDir:
            cutPlane= mc.polyCut((beseMesh + '_cageA'), ws = True, cd = c , df = True , ch =True)
            mc.setAttr((cutPlane[0]+'.cutPlaneCenterX'), mirrorPivot[0])
            mc.setAttr((cutPlane[0]+'.cutPlaneCenterY'), mirrorPivot[1])
            mc.setAttr((cutPlane[0]+'.cutPlaneCenterZ'), mirrorPivot[2])
        mc.DeleteHistory(beseMesh + '_cageA')
        mc.move(mirrorPivot[0],mirrorPivot[1],mirrorPivot[2], (beseMesh + '_cageA.scalePivot'),(beseMesh + '_cageA.rotatePivot'), absolute=True)
        mc.makeIdentity((beseMesh + '_cageA'),apply= True, t= 1, r =1, s =1, n= 0,pn=1)
        mc.setAttr((beseMesh + '_cageA.scaleX'), 1.01)
        mc.setAttr((beseMesh + '_cageA.scaleY'), 1.01)
        mc.setAttr((beseMesh + '_cageA.scaleZ'), 1.01)
        mc.setAttr((beseMesh + '_cageA.visibility'), 0)
        mc.setAttr((beseMesh + '_cageAShape.castsShadows'), 0)
        mc.setAttr((beseMesh + '_cageAShape.receiveShadows'), 0)
        mc.makeIdentity((beseMesh + '_cageA'),apply= True, t= 1, r =1, s =1, n= 0,pn=1)
        if not mc.objExists('CageShader'):
            lambertNode = mc.shadingNode("lambert", asShader=1)
            mc.rename(lambertNode,('CageShader'))
            sgNode = mc.sets(renderable=1, noSurfaceShader=1, empty=1, name= 'CageShaderSG')
            mc.connectAttr('CageShader.color', sgNode+".surfaceShader",f=1)
            mc.connectControl( 'CageColorSlider', 'CageShader.color')
            mc.colorSliderGrp('CageColorSlider', e=True, rgb=(0.5, 0, 0))
        cageColor = mc.colorSliderGrp('CageColorSlider', q=True, rgb=True)
        cageTrans = mc.floatSlider('CageTransparentSlider', q=True, value = True)
        mc.setAttr('CageShader.transparency', cageTrans,cageTrans,cageTrans, type= 'double3')
        mc.setAttr('CageShader.color',  cageColor[0],cageColor[1],cageColor[2], type= 'double3')
        mc.sets((beseMesh +'_cageA'), e=1, fe= 'CageShaderSG')
        mc.modelEditor('modelPanel4', e=True, udm=False )
        mc.CreateEmptyGroup()
        mc.rename((beseMesh +'_cageGrp'))
        mc.parent((beseMesh +'_cageA'), (beseMesh +'_cageGrp'))
        mc.parent((beseMesh +'_cageGrp'), (beseMesh +'BoolGrp'))
        if not mc.objExists('BoolSymmetryCage'):
            mc.createDisplayLayer(name = ('BoolSymmetryCage'))
        mc.editDisplayLayerMembers( ('BoolSymmetryCage'),(beseMesh +'_cageGrp'))
        mc.setAttr(('BoolSymmetryCage.displayType'),2)
    
        newNode = mc.duplicate((beseMesh + '_cageA'),rr=True)
        mc.setAttr((newNode[0]+'.scaleX'), -1)
        newNode = mc.duplicate((beseMesh + '_cageA'),rr=True)
        mc.setAttr((newNode[0]+'.scaleY'), -1)
        newNode = mc.duplicate((beseMesh + '_cageA'),rr=True)
        mc.setAttr((newNode[0]+'.scaleZ'), -1)
        newNode = mc.duplicate((beseMesh + '_cageA'),rr=True)
        mc.setAttr((newNode[0]+'.scaleX'), -1)
        mc.setAttr((newNode[0]+'.scaleY'), -1)
        newNode = mc.duplicate((beseMesh + '_cageA'),rr=True)
        mc.setAttr((newNode[0]+'.scaleX'), -1)
        mc.setAttr((newNode[0]+'.scaleZ'), -1)
        newNode = mc.duplicate((beseMesh + '_cageA'),rr=True)
        mc.setAttr((newNode[0]+'.scaleY'), -1)
        mc.setAttr((newNode[0]+'.scaleZ'), -1)
        newNode = mc.duplicate((beseMesh + '_cageA'),rr=True)
        mc.setAttr((newNode[0]+'.scaleX'), -1)
        mc.setAttr((newNode[0]+'.scaleY'), -1)
        mc.setAttr((newNode[0]+'.scaleZ'), -1)
    
    
        if mc.attributeQuery('symmetryX', node = beseMesh, ex=True ):
            getSymX =  mc.getAttr(beseMesh+'.symmetryX')
        if mc.attributeQuery('symmetryY', node = beseMesh, ex=True ):
            getSymY =  mc.getAttr(beseMesh+'.symmetryY')
        if mc.attributeQuery('symmetryZ', node = beseMesh, ex=True ):
            getSymZ =  mc.getAttr(beseMesh+'.symmetryZ')
    
        if getSymX != 0 or getSymY != 0 or getSymZ != 0:
            cageList = mc.ls((beseMesh + '_cageA*'),type='transform')
    
            if getSymX == 1:
                for c in cageList:
                    checkX = mc.getAttr(c+'.scaleX')
                    if checkX == -1:
                        mc.setAttr((c+'.visibility'),1)
    
    
            elif getSymX == -1:
                for c in cageList:
                    checkX = mc.getAttr(c+'.scaleX')
                    if checkX == 1:
                        mc.setAttr((c+'.visibility'),1)
    
    
            if getSymY == 1:
                for c in cageList:
                    checkY = mc.getAttr(c+'.scaleY')
                    if checkY == -1:
                        mc.setAttr((c+'.visibility'),1)
    
    
            elif getSymY == -1:
                for c in cageList:
                    checkY = mc.getAttr(c+'.scaleY')
                    if checkY == 1:
                        mc.setAttr((c+'.visibility'),1)
    
            if getSymZ == 1:
                for c in cageList:
                    checkY = mc.getAttr(c+'.scaleZ')
                    if checkY == -1:
                        mc.setAttr((c+'.visibility'),1)
    
    
            elif getSymZ == -1:
                for c in cageList:
                    checkY = mc.getAttr(c+'.scaleZ')
                    if checkY == 1:
                        mc.setAttr((c+'.visibility'),1)
        mc.select(cl=True)

def boolSymmetryReset():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        symmNode = mc.listConnections(mc.listHistory((beseMesh+'_bool'),af=1),type='polyMirror')
        if symmNode != None :
            if len(symmNode)>0:
                mc.delete(symmNode)
    
        resetBoolSymmetryUI()
        if mc.objExists(beseMesh +'_cageGrp'):
            mc.delete(beseMesh +'_cageGrp')


def resetBoolSymmetryUI():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if not mc.attributeQuery('symmetryX', node = beseMesh, ex=True ):
            mc.addAttr(beseMesh, ln='symmetryX', at = "long" )
        mc.setAttr((beseMesh+'.symmetryX'),0)
        if not mc.attributeQuery('symmetryY', node = beseMesh, ex=True ):
            mc.addAttr(beseMesh, ln='symmetryY', at = "long" )
        mc.setAttr((beseMesh+'.symmetryY'),0)
        if not mc.attributeQuery('symmetryZ', node = beseMesh, ex=True ):
            mc.addAttr(beseMesh, ln='symmetryZ', at = "long" )
        mc.setAttr((beseMesh+'.symmetryZ'),0)
        mc.button('symmXButtonP',e=True, bgc = [0.14, 0.14, 0.14])
        mc.button('symmYButtonP',e=True, bgc = [0.14, 0.14, 0.14])
        mc.button('symmZButtonP',e=True, bgc = [0.14, 0.14, 0.14])
        mc.button('symmXButtonN',e=True, bgc = [0.14, 0.14, 0.14])
        mc.button('symmYButtonN',e=True, bgc = [0.14, 0.14, 0.14])
        mc.button('symmZButtonN',e=True, bgc = [0.14, 0.14, 0.14])


def boolSymmetryFreeze():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    symmNode = mc.listConnections(mc.listHistory((beseMesh+'_bool'),af=1),type='polyMirror')
    if symmNode != None  and len(symmNode)>0:
        bakeCutter('all')
        symmetryCutter()
        symmetryBase()
        mc.select(cl=True)
        restoreCutter()
        resetBoolSymmetryUI()
        if mc.objExists(beseMesh +'_cageGrp'):
            mc.delete(beseMesh +'_cageGrp')

def symmetryBase():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    getSymX = 0
    getSymY = 0
    getSymZ = 0

    mc.setAttr((beseMesh+'.visibility'), 1)
    mirrorPivot = mc.objectCenter(beseMesh, gl=True)
    mc.setAttr((beseMesh+'.visibility'), 0)


    if mc.attributeQuery('symmetryX', node = beseMesh, ex=True ):
        getSymX =  mc.getAttr(beseMesh+'.symmetryX')
    if mc.attributeQuery('symmetryY', node = beseMesh, ex=True ):
        getSymY =  mc.getAttr(beseMesh+'.symmetryY')
    if mc.attributeQuery('symmetryZ', node = beseMesh, ex=True ):
        getSymZ =  mc.getAttr(beseMesh+'.symmetryZ')

    if getSymX != 0 or getSymY != 0 or getSymZ != 0:
        if getSymX == 1:
            mc.polyMirrorFace(beseMesh, cutMesh = 1, axis = 0 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1,  ws =1, p = mirrorPivot)
        elif  getSymX == -1:
            mc.polyMirrorFace(beseMesh, cutMesh = 1, axis = 0 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =1, p = mirrorPivot)

        if getSymY == 1:
            mc.polyMirrorFace(beseMesh, cutMesh = 1, axis = 1 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1,  ws =1, p = mirrorPivot)
        elif  getSymY == -1:
            mc.polyMirrorFace(beseMesh, cutMesh = 1, axis = 1 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =1, p = mirrorPivot)

        if getSymZ == 1:
            mc.polyMirrorFace(beseMesh, cutMesh = 1, axis = 2 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1,  ws =1, p = mirrorPivot)
        elif  getSymZ == -1:
            mc.polyMirrorFace(beseMesh, cutMesh = 1, axis = 2 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1,  ws =1, p = mirrorPivot)
        mc.DeleteHistory()

def boolSymmetry(axis,dir):
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selPoly = beseMesh+'_bool'
    
        if not mc.attributeQuery('symmetryX', node = beseMesh, ex=True ):
            mc.addAttr(beseMesh, ln='symmetryX', at = "long" )
            mc.setAttr((beseMesh+'.symmetryX'),0)
        if not mc.attributeQuery('symmetryY', node = beseMesh, ex=True ):
            mc.addAttr(beseMesh, ln='symmetryY', at = "long" )
            mc.setAttr((beseMesh+'.symmetryY'),0)
        if not mc.attributeQuery('symmetryZ', node = beseMesh, ex=True ):
            mc.addAttr(beseMesh, ln='symmetryZ', at = "long" )
            mc.setAttr((beseMesh+'.symmetryZ'),0)
    
        mc.setAttr((beseMesh+'.visibility'), 1)
        mirrorPivot = mc.objectCenter(beseMesh, gl=True)
        mc.setAttr((beseMesh+'.visibility'), 0)
    
    
        mirrorName = []
        checkSymm = 0
        symmNode = mc.listConnections(mc.listHistory((selPoly),af=1),type='polyMirror')
        if axis == 'x' :
            checkDirState=[]
            if symmNode != None:
                for s in symmNode:
                    if 'symmetryX' in s:
                        checkSymm = 1
                        checkDirState = s
            if checkSymm == 0:
                if dir == 1:
                    mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 0 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                    mc.setAttr((beseMesh+'.symmetryX'),1)
                    mc.button('symmXButtonP',e=True, bgc = [0.34, 0.14, 0.14])
                    mc.rename(mirrorName[0],(beseMesh + '_symmetryXP'))
                else:
                    mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 0 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                    mc.setAttr((beseMesh+'.symmetryX'),-1)
                    mc.button('symmXButtonN',e=True, bgc = [0.34, 0.14, 0.14])
                    mc.rename(mirrorName[0],(beseMesh + '_symmetryXN'))
            else:
                if mc.objExists((beseMesh +'_symmetryXP')):
                    mc.delete(beseMesh + '_symmetryXP')
                if mc.objExists((beseMesh +'_symmetryXN')):
                    mc.delete(beseMesh + '_symmetryXN')
                mc.button('symmXButtonP',e=True, bgc = [0.28,0.28,0.28])
                mc.button('symmXButtonN',e=True, bgc = [0.28,0.28,0.28])
                if dir == 1:
                    if checkDirState == (beseMesh + '_symmetryXP'):# same button press, remove it
                        mc.setAttr((beseMesh+'.symmetryX'),0)
                    else:
                        mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 0 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                        mc.setAttr((beseMesh+'.symmetryX'),1)
                        mc.button('symmXButtonP',e=True, bgc = [0.34, 0.14, 0.14])
                        mc.rename(mirrorName[0],(beseMesh + '_symmetryXP'))
                else:
                    if checkDirState == (beseMesh + '_symmetryXN'):# same button press, remove it
                        mc.setAttr((beseMesh+'.symmetryX'),0)
                    else:
                        mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 0 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                        mc.setAttr((beseMesh+'.symmetryX'),-1)
                        mc.button('symmXButtonN',e=True, bgc = [0.34, 0.14, 0.14])
                        mc.rename(mirrorName[0],(beseMesh + '_symmetryXN'))
    
    
    
    
        elif axis == 'y' :
            checkDirState=[]
            if symmNode != None:
                for s in symmNode:
                    if 'symmetryY' in s:
                        checkSymm = 1
                        checkDirState = s
            if checkSymm == 0:
                if dir == 1:
                    mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 1 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                    mc.setAttr((beseMesh+'.symmetryY'),1)
                    mc.button('symmYButtonP',e=True, bgc = [0.14, 0.34, 0.14])
                    mc.rename(mirrorName[0],(beseMesh + '_symmetryYP'))
                else:
                    mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 1 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                    mc.setAttr((beseMesh+'.symmetryY'),-1)
                    mc.button('symmYButtonN',e=True, bgc = [0.14, 0.34, 0.14])
                    mc.rename(mirrorName[0],(beseMesh + '_symmetryYN'))
    
    
            else:
                if mc.objExists((beseMesh +'_symmetryYP')):
                    mc.delete(beseMesh + '_symmetryYP')
                if mc.objExists((beseMesh +'_symmetryYN')):
                    mc.delete(beseMesh + '_symmetryYN')
                mc.button('symmYButtonP',e=True, bgc = [0.28,0.28,0.28])
                mc.button('symmYButtonN',e=True, bgc = [0.28,0.28,0.28])
                if dir == 1:
                    if checkDirState == (beseMesh + '_symmetryYP'):# same button press, remove it
                        mc.setAttr((beseMesh+'.symmetryY'),0)
                    else:
                        mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 1 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                        mc.setAttr((beseMesh+'.symmetryY'),1)
                        mc.button('symmYButtonP',e=True, bgc = [0.14, 0.34, 0.14])
                        mc.rename(mirrorName[0],(beseMesh + '_symmetryYP'))
                else:
                    if checkDirState == (beseMesh + '_symmetryYN'):# same button press, remove it
                        mc.setAttr((beseMesh+'.symmetryY'),0)
                    else:
                        mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 1 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                        mc.setAttr((beseMesh+'.symmetryY'),-1)
                        mc.button('symmYButtonN',e=True, bgc = [0.14, 0.34, 0.14])
                        mc.rename(mirrorName[0],(beseMesh + '_symmetryYN'))
    
    
        else:
            checkDirState=[]
            if symmNode != None:
                for s in symmNode:
                    if 'symmetryZ' in s:
                        checkSymm = 1
                        checkDirState = s
            if checkSymm == 0:
                if dir == 1:
                    mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 2 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                    mc.setAttr((beseMesh+'.symmetryZ'),1)
                    mc.button('symmZButtonP',e=True, bgc = [0.14, 0.14, 0.34])
                    mc.rename(mirrorName[0],(beseMesh + '_symmetryZP'))
                else:
                    mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 2 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                    mc.setAttr((beseMesh+'.symmetryZ'),-1)
                    mc.button('symmZButtonN',e=True, bgc = [0.14, 0.14, 0.34])
                    mc.rename(mirrorName[0],(beseMesh + '_symmetryZN'))
    
            else:
                if mc.objExists((beseMesh +'_symmetryZP')):
                    mc.delete(beseMesh + '_symmetryZP')
                if mc.objExists((beseMesh +'_symmetryZN')):
                    mc.delete(beseMesh + '_symmetryZN')
                mc.button('symmZButtonP',e=True, bgc = [0.28,0.28,0.28])
                mc.button('symmZButtonN',e=True, bgc = [0.28,0.28,0.28])
                if dir == 1:
                    if checkDirState == (beseMesh + '_symmetryZP'):# same button press, remove it
                        mc.setAttr((beseMesh+'.symmetryZ'),0)
                    else:
                        mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 2 , axisDirection = 1 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                        mc.setAttr((beseMesh+'.symmetryZ'),1)
                        mc.button('symmZButtonP',e=True, bgc = [0.14, 0.14, 0.34])
                        mc.rename(mirrorName[0],(beseMesh + '_symmetryZP'))
                else:
                    if checkDirState == (beseMesh + '_symmetryZN'):# same button press, remove it
                        mc.setAttr((beseMesh+'.symmetryZ'),0)
                    else:
                        mirrorName = mc.polyMirrorFace(selPoly, cutMesh = 1, axis = 2 , axisDirection = 0 , mergeMode = 1 , mergeThresholdType = 0 , mergeThreshold = 0.001 , mirrorAxis = 2, mirrorPosition= 0, smoothingAngle = 30, flipUVs = 0, ch=1, ws =True, p = mirrorPivot)
                        mc.setAttr((beseMesh+'.symmetryZ'),-1)
                        mc.button('symmZButtonN',e=True, bgc = [0.14, 0.14, 0.34])
                        mc.rename(mirrorName[0],(beseMesh + '_symmetryZN'))
    
    
        boolSymmetryCage()

def loadSymmetryState():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        symmNode = mc.listConnections(mc.listHistory((beseMesh+'_bool'),af=1),type='polyMirror')
        mc.button('symmXButtonP',e=True, bgc = [0.28, 0.28, 0.28])
        mc.button('symmYButtonP',e=True, bgc = [0.28, 0.28, 0.28])
        mc.button('symmZButtonP',e=True, bgc = [0.28, 0.28, 0.28])
        mc.button('symmXButtonN',e=True, bgc = [0.28, 0.28, 0.28])
        mc.button('symmYButtonN',e=True, bgc = [0.28, 0.28, 0.28])
        mc.button('symmZButtonN',e=True, bgc = [0.28, 0.28, 0.28])
    
        checkState = 0
        if symmNode != None:
            for s in symmNode:
                if 'symmetryXP' in s :
                    mc.button('symmXButtonP',e=True, bgc = [0.34, 0.14, 0.14])
                    checkState = 1
                elif  'symmetryXN' in s :
                    mc.button('symmXButtonN',e=True, bgc = [0.34, 0.14, 0.14])
                    checkState = 1
                elif  'symmetryYP' in s :
                    mc.button('symmYButtonP',e=True, bgc = [0.14, 0.34, 0.14])
                    checkState = 1
                elif  'symmetryYN' in s :
                    mc.button('symmYButtonN',e=True, bgc = [0.14, 0.34, 0.14])
                    checkState = 1
                elif  'symmetryZP' in s :
                    mc.button('symmZButtonP',e=True, bgc = [0.14, 0.14, 0.34])
                    checkState = 1
                elif  'symmetryZN' in s :
                    mc.button('symmZButtonN',e=True, bgc = [0.14, 0.14, 0.34])
                    checkState = 1


def screenRes():
    windowUnder = mc.getPanel(withFocus=True)
    if 'modelPanel' not in windowUnder:
        windowUnder = 'modelPanel4'
    viewNow = omui.M3dView()
    omui.M3dView.getM3dViewFromModelEditor(windowUnder, viewNow)
    screenW = omui.M3dView.portWidth(viewNow)
    screenH = omui.M3dView.portHeight(viewNow)
    return screenW,screenH

def worldSpaceToImageSpace(cameraName, worldPoint):
    resWidth,resHeight = screenRes()
    selList = om.MSelectionList()
    selList.add(cameraName)
    dagPath = om.MDagPath()
    selList.getDagPath(0,dagPath)
    dagPath.extendToShape()
    camInvMtx = dagPath.inclusiveMatrix().inverse()
    fnCam = om.MFnCamera(dagPath)
    mFloatMtx = fnCam.projectionMatrix()
    projMtx = om.MMatrix(mFloatMtx.matrix)
    mPoint = om.MPoint(worldPoint[0],worldPoint[1],worldPoint[2]) * camInvMtx * projMtx;
    x = (mPoint[0] / mPoint[3] / 2 + .5) * resWidth
    y = (mPoint[1] / mPoint[3] / 2 + .5) * resHeight
    return [x,y]

def evenObjLineUp(dir):
    lineupList = mc.ls(sl=1,fl=1)
    if lineupList:
        view = omui.M3dView.active3dView()
        cam = om.MDagPath()
        view.getCamera(cam)
        camPath = cam.fullPathName()
        cameraTrans = mc.listRelatives(camPath,type='transform',p=True)
        dataX = {}
        dataY = {}
        for l in lineupList:
            bbox = mc.xform(l, q=True, ws=True, piv=True)
            pos2D = worldSpaceToImageSpace(cameraTrans[0],(bbox[0],bbox[1],bbox[2]))
            dataX.update( {l : pos2D[0]} )
            dataY.update( {l : pos2D[1]} )
    
        if dir == 'x' :
            score = OrderedDict(sorted(dataX.items(), key = lambda fd: fd[1],reverse = False))
        else:
            score = OrderedDict(sorted(dataY.items(), key = lambda fd: fd[1],reverse = False))
    
        #use fd[0] to get name order, fd[1] to get key order
        orderList = []
        for key in score:
            orderList.append(key)
        # get distanceGap
        posStart = mc.xform(orderList[0], q=True, ws=True, piv=True)
        posEnd = mc.xform(orderList[-1], q=True, ws=True, piv=True)
        gapX = (posEnd[0] - posStart[0]) / (len(orderList) - 1)
        gapY = (posEnd[1] - posStart[1]) / (len(orderList) - 1)
        gapZ = (posEnd[2] - posStart[2]) / (len(orderList) - 1)
    
    
        rotStartX = mc.getAttr(orderList[0]+'.rotateX')
        rotStartY = mc.getAttr(orderList[0]+'.rotateY')
        rotStartZ = mc.getAttr(orderList[0]+'.rotateZ')
        rotEndX = mc.getAttr(orderList[-1]+'.rotateX')
        rotEndY = mc.getAttr(orderList[-1]+'.rotateY')
        rotEndZ = mc.getAttr(orderList[-1]+'.rotateZ')
    
        rotX = (rotEndX - rotStartX) /   (len(orderList) - 1)
        rotY = (rotEndY - rotStartY) /   (len(orderList) - 1)
        rotZ = (rotEndZ - rotStartZ) /   (len(orderList) - 1)
    
    
    
        for i in range(1,(len(orderList)-1)):
            mc.move( (posStart[0] + (i *gapX)) , (posStart[1] + (i *gapY)), (posStart[2] + (i *gapZ)), orderList[i], rpr = True ,absolute=True )
            mc.setAttr( (orderList[i] + '.rotateX'), ((i *rotX)+ rotStartX) )
            mc.setAttr( (orderList[i] + '.rotateY'), ((i *rotY)+ rotStartY) )
            mc.setAttr( (orderList[i] + '.rotateZ'), ((i *rotZ)+ rotStartZ) )


def borderAlginBBoxDivUpdate():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if not mc.objExists(beseMesh +'_borderBox'):
        borderAlginBBoxCreate()
    checkDiv =  mc.intSliderGrp('bboxDivSlider', q=True, v = True)
    mc.setAttr((beseMesh + '_bbox.subdivisionsDepth') , checkDiv)
    mc.setAttr((beseMesh + '_bbox.subdivisionsWidth') , checkDiv)
    mc.setAttr((beseMesh + '_bbox.subdivisionsHeight'), checkDiv)

def borderAlginBBoxCreate():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    selStore = mc.ls(sl=True,fl=True)
    checkDiv =  mc.intSliderGrp('bboxDivSlider', q=True, v = True)
    if not mc.objExists(beseMesh +'_borderBoxGrp') and not mc.objExists(beseMesh +'_borderBox'):
        tempLattice = mc.lattice(beseMesh,divisions =(2, 2, 2), objectCentered = True, ldv = (2, 2 ,2))
        BBcenter = mc.xform(tempLattice[1],q =True, t=True)
        BBrotate = mc.xform(tempLattice[1],q =True, ro=True)
        BBscale  = mc.xform(tempLattice[1],q =True, r=True, s=True)
        BBcube = mc.polyCube(w =1, h =1, d =1, sx= checkDiv, sy= checkDiv, sz= checkDiv, ax= (0, 1, 0), ch = 1)
        mc.rename(BBcube[0],(beseMesh+'_borderBox'))
        mc.rename(BBcube[1],(beseMesh+'_bbox'))

        mc.xform((beseMesh+'_borderBox'), t = (BBcenter[0], BBcenter[1],BBcenter[2]))
        mc.xform((beseMesh+'_borderBox'), ro = (BBrotate[0], BBrotate[1],BBrotate[2]))
        mc.xform((beseMesh+'_borderBox'), s = (BBscale[0], BBscale[1],BBscale[2]))
        mc.delete(tempLattice)

        mc.group()
        mc.rename(beseMesh+'_borderBoxGrp')
        mc.parent((beseMesh+'_borderBoxGrp'), (beseMesh+'BoolGrp'))
        if not mc.objExists('BorderBox'):
            mc.createDisplayLayer(name = ('BorderBox'))
        mc.editDisplayLayerMembers( ('BorderBox'),(beseMesh+'_borderBoxGrp'))
        mc.setAttr(('BorderBox.displayType'),1)
    mc.select(selStore)

def borderAlginBBoxToggle():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    selStore = mc.ls(sl=True,fl=True)
    if not mc.objExists(beseMesh +'_borderBoxGrp') and not mc.objExists(beseMesh +'_borderBox'):
        borderAlginBBoxCreate()
        mc.button('borderAlginButton',e=True, bgc =  [0.3,0.5,0.6])
        mc.makeLive(  beseMesh +'_borderBox' )
        mc.manipMoveContext('Move',e=True, snapLivePoint= True)
    else:
        mc.delete(beseMesh +'_borderBoxGrp')
        mc.button('borderAlginButton',e=True, bgc =  [0.28,0.28,0.28])
        mc.makeLive( none=True )
        mc.manipMoveContext('Move',e=True, snapLivePoint= False)
    mc.select(selStore)

def toggleAxisButton(dir):
    if dir == "X":
        checkStateX = mc.button('toggleAxisX', q=True , bgc =True )
        if (checkStateX[0] < 0.285):
            mc.button('toggleAxisX', e=True , bgc = [.3, 0, 0] )
            mc.button('toggleAxisXYZ', e=True ,bgc = [0.28,0.28,0.28]  )
        else:
             mc.button('toggleAxisX', e=True ,bgc = [0.28,0.28,0.28]  )
    if dir == "Y":
        checkStateY = mc.button('toggleAxisY', q=True , bgc =True )
        if (checkStateY[1] < 0.285):
            mc.button('toggleAxisY', e=True , bgc = [0, 0.3, 0] )
            mc.button('toggleAxisXYZ', e=True ,bgc = [0.28,0.28,0.28]  )
        else:
             mc.button('toggleAxisY', e=True ,bgc = [0.28,0.28,0.28]  )
    if dir == "Z":
        checkStateZ = mc.button('toggleAxisZ', q=True , bgc =True )
        if (checkStateZ[2] < 0.285):
            mc.button('toggleAxisZ', e=True , bgc = [0, 0, 0.3] )
            mc.button('toggleAxisXYZ', e=True ,bgc = [0.28,0.28,0.28]  )
        else:
             mc.button('toggleAxisZ', e=True ,bgc = [0.28,0.28,0.28]  )

    if dir == "XYZ":
        checkState = mc.button('toggleAxisXYZ', q=True , bgc =True )
        if (checkState[0] < 0.285):
            mc.button('toggleAxisXYZ', e=True , bgc = [0.3, 0.5, 0.6] )
            mc.button('toggleAxisX', e=True ,bgc = [0.28,0.28,0.28]  )
            mc.button('toggleAxisY', e=True ,bgc = [0.28,0.28,0.28]  )
            mc.button('toggleAxisZ', e=True ,bgc = [0.28,0.28,0.28]  )

        else:
             mc.button('toggleAxisXYZ', e=True ,bgc = [0.28,0.28,0.28]  )
             mc.button('toggleAxisX', e=True , bgc = [.3, 0, 0] )

    checkStateX = mc.button('toggleAxisX', q=True , bgc =True )
    checkStateY = mc.button('toggleAxisY', q=True , bgc =True )
    checkStateZ = mc.button('toggleAxisZ', q=True , bgc =True )
    if (checkStateX[0] < 0.285) and (checkStateY[1] < 0.285) and (checkStateZ[2] < 0.285):
        mc.button('toggleAxisXYZ', e=True , bgc = [0.3, 0.5, 0.6] )
    elif (checkStateX[0] > 0.285) and (checkStateY[1] > 0.285) and (checkStateZ[2] > 0.285):
        mc.button('toggleAxisXYZ', e=True , bgc = [0.3, 0.5, 0.6] )
        mc.button('toggleAxisX', e=True ,bgc = [0.28,0.28,0.28]  )
        mc.button('toggleAxisY', e=True ,bgc = [0.28,0.28,0.28]  )
        mc.button('toggleAxisZ', e=True ,bgc = [0.28,0.28,0.28]  )


def alignSelCutter():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        cutterList = mc.ls(type='transform',os=1)
        if len(cutterList) == 2:
            currentX = mc.getAttr(cutterList[0]+'.translateX')
            currentY = mc.getAttr(cutterList[0]+'.translateY')
            currentZ = mc.getAttr(cutterList[0]+'.translateZ')
            mc.select(cutterList[0],cutterList[1],r=True)
            mc.MatchTranslation()
            checkState = mc.button('toggleAxisXYZ', q=True , bgc =True )
            if checkState[0] < 0.285:
                checkStateX = mc.button('toggleAxisX', q=True , bgc =True )
                if checkStateX[0] <0.285:
                    mc.setAttr((cutterList[0]+'.translateX'),currentX)
    
                checkStateY = mc.button('toggleAxisY', q=True , bgc =True )
                if checkStateY[1] <0.285:
                    mc.setAttr((cutterList[0]+'.translateY'),currentY)
                checkStateZ = mc.button('toggleAxisZ', q=True , bgc =True )
                if checkStateZ[2] <0.285:
                    mc.setAttr((cutterList[0]+'.translateZ'),currentZ)
        mc.select(cutterList[0])

def alignLastCutter():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selCutter = mc.ls(sl=1,fl=1)
        mc.select(beseMesh+'_cutterGrp')
        mc.select(hi=True)
        mc.select((beseMesh+'_cutterGrp'),d=True)
        mc.select(selCutter,d=True)
        cutterList = mc.ls(sl=1,fl=1,type='transform')
        if len(cutterList) > 0:
            lastCutter = cutterList[-1]
            for s in selCutter:
                currentX = mc.getAttr(s+'.translateX')
                currentY = mc.getAttr(s+'.translateY')
                currentZ = mc.getAttr(s+'.translateZ')
                mc.select(s,lastCutter,r=True)
                mc.MatchTranslation()
                checkState = mc.button('toggleAxisXYZ', q=True , bgc =True )
                if checkState[0] < 0.285:
                    checkStateX = mc.button('toggleAxisX', q=True , bgc =True )
                    if checkStateX[0] <0.285:
                        mc.setAttr((s+'.translateX'),currentX)
    
                    checkStateY = mc.button('toggleAxisY', q=True , bgc =True )
                    if checkStateY[1] <0.285:
                        mc.setAttr((s+'.translateY'),currentY)
                    checkStateZ = mc.button('toggleAxisZ', q=True , bgc =True )
                    if checkStateZ[2] <0.285:
                        mc.setAttr((s+'.translateZ'),currentZ)
        mc.select(selCutter)

def alignCutterToBase():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selCutters = mc.ls(sl=True,fl=True)
        if len(selCutters) > 0:
            if mc.objExists('tempSnap'):
                mc.delete('tempSnap')
            if mc.objExists(beseMesh+'_borderBox') == 0:
                borderAlginBBoxToggle()
    
            borderBox = beseMesh + '_borderBox'
            cvNo = mc.polyEvaluate(borderBox, v=True )
    
            for s in selCutters:
                checkMinDistance = SNAP_SEARCH_INIT_DIST
                cutterPosition = mc.xform(s, q =True, sp=True,ws=True)
                closetestPos = [0,0,0]
                currentX = mc.getAttr(s+'.translateX')
                currentY = mc.getAttr(s+'.translateY')
                currentZ = mc.getAttr(s+'.translateZ')
                for i in range(cvNo):
                    cvBboxPosition = mc.pointPosition(borderBox+'.vtx[' + str(i) + ']',w=1)
                    checkDistance = _distance_3d(cutterPosition, cvBboxPosition)
                    if checkDistance < checkMinDistance:
                        checkMinDistance = checkDistance
                        closetestPos = cvBboxPosition
                mc.spaceLocator( p=(closetestPos[0], closetestPos[1], closetestPos[2]),n='tempSnap')
                mc.CenterPivot()
                mc.select(s,'tempSnap',r=True)
                mc.MatchTranslation()
                mc.delete('tempSnap')
                checkState = mc.button('toggleAxisXYZ', q=True , bgc =True )
                if checkState[0] < 0.285:
                    checkStateX = mc.button('toggleAxisX', q=True , bgc =True )
                    if checkStateX[0] <0.285:
                        mc.setAttr((s+'.translateX'),currentX)
    
                    checkStateY = mc.button('toggleAxisY', q=True , bgc =True )
                    if checkStateY[1] <0.285:
                        mc.setAttr((s+'.translateY'),currentY)
    
                    checkStateZ = mc.button('toggleAxisZ', q=True , bgc =True )
                    if checkStateZ[2] <0.285:
                        mc.setAttr((s+'.translateZ'),currentZ)
            #borderAlginBBoxToggle()
            mc.select(selCutters)

def combineSelCutters():#work with different type of OP, but mixing type may be cause unexpect result
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selList = mc.ls(sl=True,fl=True)
        restoreMissingGrps()
        getOpType = ''
        if len(selList) > 1:
            #bake array
            for s in selList:
                if mc.objExists(s):
                    mc.select(s)
                    myType = checkInstType()
                    if myType[1] != 'new':
                        instBake()
                        newNode = mc.ls(sl=1,fl=1)
                        selList.append(newNode[0])
            subsGrp = []
            unionGrp = []
            cutGrp = []
            for b in selList:
                longName = '|' +  beseMesh  + 'BoolGrp' + '|' + beseMesh+'_cutterGrp|' + b
                if mc.objExists(longName):
                    checkOP = mc.getAttr(longName + '.cutterOp')
                    if checkOP == 'subs':
                        subsGrp.append(b)
                    elif checkOP == 'union':
                        unionGrp.append(b)
                    elif checkOP == 'cut':
                        cutGrp.append(b)
            if (len(subsGrp) + len(unionGrp) + len(cutGrp))>1:
                #union each type
                selList = subsGrp
                if len(selList)> 0:
                    mc.select(selList)
                    while len(selList) > 1:
                        mc.polyCBoolOp(selList[0], selList[1], op=1, ch=1, preserveColor=0, classification=1, name=selList[0])
                        mc.DeleteHistory()
                        if mc.objExists(selList[1]):
                            mc.delete(selList[1])
                        mc.rename(selList[0])
                        selList.remove(selList[1])
                    mc.rename('subsMesh')
    
                selList = unionGrp
                if len(selList)> 0:
                    mc.select(selList)
                    while len(selList) > 1:
                        mc.polyCBoolOp(selList[0], selList[1], op=1, ch=1, preserveColor=0, classification=1, name=selList[0])
                        mc.DeleteHistory()
                        if mc.objExists(selList[1]):
                            mc.delete(selList[1])
                        mc.rename(selList[0])
                        selList.remove(selList[1])
                    mc.rename('unionMesh')
    
                selList = cutGrp
                if len(selList)> 0:
                    mc.select(selList)
                    while len(selList) > 1:
                        mc.polyCBoolOp(selList[0], selList[1], op=1, ch=1, preserveColor=0, classification=1, name=selList[0])
                        mc.DeleteHistory()
                        if mc.objExists(selList[1]):
                            mc.delete(selList[1])
                        mc.rename(selList[0])
                        selList.remove(selList[1])
                    mc.rename('cutMesh')
    
            if mc.objExists('subsMesh'):
                if mc.objExists('unionMesh'):
                    mc.polyCBoolOp('subsMesh', 'unionMesh', op=2, ch=1, preserveColor=0, classification=1, name='outMesh')
                    if mc.objExists('cutMesh'):
                        mc.polyCBoolOp('outMesh', 'cutMesh', op=1, ch=1, preserveColor=0, classification=1, name='outMesh')
                else:
                     if mc.objExists('cutMesh'):
                        mc.polyCBoolOp('subsMesh', 'cutMesh', op=1, ch=1, preserveColor=0, classification=1, name='outMesh')
                newCutter = mc.ls(sl=1,fl=1)
                mc.DeleteHistory('outMesh')
                useOwnCutterShape()
                cutterType('subs')
    
            else:
                if mc.objExists('unionMesh'):
                    if mc.objExists('cutMesh'):
                        mc.polyCBoolOp('unionMesh', 'cutMesh', op=2, ch=1, preserveColor=0, classification=1, name='outMesh')
                newCutter = mc.ls(sl=1,fl=1)
                mc.DeleteHistory('outMesh')
                useOwnCutterShape()
                cutterType('union')
    
            cleanList = ['subsMesh','cutMesh','unionMesh','outMesh']
            for l in cleanList:
                if mc.objExists(l):
                    mc.delete(l)
        else:
            print ('need more then one cutter!')

def recreateBool():
    #recreate bool
    global sceneSize
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        cleanList = ['_mySubs','_myUnion','_preSubBox','_preUnionBox','_myBoolUnion','_afterSubBox','_myBoolSub','_myCut']
        for l in cleanList:
            if mc.objExists(beseMesh + l):
                mc.delete(beseMesh + l)
        if mc.objExists((beseMesh +'_bool')) ==0:
            mc.polyCube(w = sceneSize, h=sceneSize, d=sceneSize ,sx =1 ,sy= 1, sz= 1)
            mc.rename(beseMesh +'_preSubBox')
    
            mc.polyCube(w = sceneSize, h=sceneSize, d=sceneSize ,sx =1 ,sy= 1, sz= 1)
            mc.rename(beseMesh +'_afterSubBox')
    
            mc.polyCube(w = sceneSize, h=sceneSize, d=sceneSize ,sx =1 ,sy= 1, sz= 1)
            mc.rename(beseMesh +'_preUnionBox')
    
            subNode= mc.polyCBoolOp((beseMesh ), (beseMesh +'_preSubBox') , op= 2, ch= 1, preserveColor= 0, classification= 1, name= (beseMesh +'_bool'))
            mc.rename(subNode[0],(beseMesh +'_myBoolSub'))
    
            unionNode = mc.polyCBoolOp((beseMesh +'_myBoolSub'), (beseMesh +'_preUnionBox') , op= 1, ch= 1, preserveColor= 0, classification= 1, name= (beseMesh +'_union'))
            mc.rename(unionNode[0],(beseMesh +'_myBoolUnion'))
    
            subNode= mc.polyCBoolOp((beseMesh +'_myBoolUnion'), (beseMesh +'_afterSubBox') , op= 2, ch= 1, preserveColor= 0, classification= 1, name= (beseMesh +'_bool'))
            mc.rename(subNode[0],(beseMesh +'_bool'))
    
        boolNode = mc.listConnections(mc.listHistory((beseMesh +'_bool'),f=1,ac=1),type='polyCBoolOp')
        boolNode = set(boolNode)
    
        #hack it by check '_', this is used by other group
        listClean = []
        for b in boolNode:
            if '_' not in b:
                listClean.append(b)
    
        if len(listClean) == 3:
            for l in listClean:
                checkOp = mc.getAttr( l +'.operation')
                if checkOp == 2:
                    if mc.objExists(beseMesh +'_mySubs'):
                        mc.rename(l,(beseMesh +'_myCut'))
                    else:
                        mc.rename(l,(beseMesh +'_mySubs'))
                else:
                    mc.rename(l,(beseMesh +'_myUnion'))
    
        mc.setAttr((beseMesh + '.visibility'), 0)
        mc.setAttr((beseMesh+'Shape.intermediateObject'), 0)
    
        baseShapeNode = mc.listRelatives(beseMesh, f = True)
        mc.parent(baseShapeNode, beseMesh+'BoolGrp')
        mc.delete(beseMesh)
        mc.rename(beseMesh)
    
        mc.editDisplayLayerMembers( (beseMesh +'_BoolResult'),(beseMesh +'_bool')) # store my selection into the display layer
        mc.setAttr((beseMesh +'_BoolResult.displayType'),2)
    
        checkList = ['_cutterGrp','_preSubBox','_preUnionBox','_myBoolUnion','_bool', '', '_afterSubBox','_myBoolSub' ]
        for c in checkList:
            checkGrp = mc.ls((beseMesh + c), l=True)
            if 'BoolGrp' not in checkGrp[0]:
                mc.parent(checkGrp[0],(beseMesh +'BoolGrp'))
    
        mc.select(cl=True)
        meshBBox()

def bakeCutter(mode):
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        selectedCutter = mc.ls(sl=1,fl=1)
        checkGrp = mc.ls(sl=1,fl=1,l=1)
        if mode == 'unselect' and len(selectedCutter) == 0:
            print ('nothing selected!')
        else:
            #store any symmtry
            mc.setAttr((beseMesh+'.visibility'), 1)
            mirrorPivot = mc.objectCenter(beseMesh, gl=True)
            mc.setAttr((beseMesh+'.visibility'), 0)
            getSymX = 0
            getSymY = 0
            getSymZ = 0
            if mc.attributeQuery('symmetryX', node = beseMesh, ex=True ):
                getSymX =  mc.getAttr(beseMesh+'.symmetryX')
            if mc.attributeQuery('symmetryY', node = beseMesh, ex=True ):
                getSymY =  mc.getAttr(beseMesh+'.symmetryY')
            if mc.attributeQuery('symmetryZ', node = beseMesh, ex=True ):
                getSymZ =  mc.getAttr(beseMesh+'.symmetryZ')
            #flatten all cutters
            flattenAlllCutter()
            cleanList   = []
            if mode == 'unselect':
                if beseMesh in checkGrp[0]:#check if cutter in current base mesh
                    #getList after flattern
                    for s in selectedCutter:
                        if 'ArrayGrp' in s:
                            s = s.replace("ArrayGrp", "")
                        if mc.objExists(s.split('|')[-1]):
                            cleanList.append(s.split('|')[-1])
                    tempLong = []
                    for c in cleanList:
                        longName = '|' + beseMesh + 'BoolGrp|' + beseMesh + '_cutterGrp|' + c 
                        tempLong.append(longName)
                    cleanList = tempLong    
                    mc.select(cleanList)
                    #disconnect from bool
                    for c in cleanList:
                        shapeNode = mc.listRelatives(c, f = True, shapes=True)
                        if len(shapeNode)>0:
                            listConnect = mc.connectionInfo((shapeNode[0]+'.outMesh'), dfs=True )
                            if len(listConnect)>0:
                                for a in listConnect:
                                    mc.disconnectAttr((shapeNode[0]+'.outMesh'), a)
                            listConnectMa = mc.connectionInfo((shapeNode[0]+'.worldMatrix[0]'), dfs=True )
                            if len(listConnectMa)>0:
                                for b in listConnectMa:
                                    mc.disconnectAttr((shapeNode[0]+'.worldMatrix[0]'), b)
                    # move to temp grp
                    if mc.objExists((beseMesh +'_tempStoreGrp')) == 0:
                        mc.CreateEmptyGroup()
                        mc.rename((beseMesh +'_tempStoreGrp'))
                        mc.parent((beseMesh +'_tempStoreGrp'), (beseMesh+'BoolGrp'))
                    mc.parent(cleanList , (beseMesh +'_tempStoreGrp'))
    
            #make bool mesh as new base mesh
            newMesh = mc.duplicate((beseMesh+'_bool'),rr=1)
            mc.delete(beseMesh+'_bool')
            #create Step up Group
            if mc.objExists((beseMesh +'_bakeStep')) == 0:
                mc.CreateEmptyGroup()
                mc.rename((beseMesh +'_bakeStep'))
                mc.parent((beseMesh +'_bakeStep'), (beseMesh+'BoolGrp'))
            mc.setAttr((beseMesh +'_bakeStep.visibility'),0)
    
            if mc.objExists((beseMesh +'_bakeBaseMesh')) == 0:
                #bake base mesh
                bakeMesh = mc.duplicate(beseMesh, rr=1)
                mc.delete(beseMesh)
                mc.parent(bakeMesh,(beseMesh +'_bakeStep'))
                mc.rename(bakeMesh,(beseMesh +'_bakeBaseMesh'))
                bakeShape = mc.listRelatives((beseMesh +'_bakeBaseMesh'), shapes=True,f=True)
                #mc.setAttr((bakeShape[0] + '.overrideShading'), 1)
                mc.rename(newMesh,beseMesh)
            else:
                mc.delete(beseMesh)
                mc.rename(newMesh,beseMesh)
            if mc.objExists(beseMesh +'_myBool'):
                mc.delete(beseMesh+'_myBool')
            #reNumber
            mc.select((beseMesh+'_bakeStep'), hi=True)
            mc.select((beseMesh+'_bakeStep'),(beseMesh +'_bakeBaseMesh'),d=True)
            existCutterList = mc.ls(sl=1,fl=1,type='transform')
            #start rename old cutters
            mc.select((beseMesh+'_cutterGrp'), hi=True)
            mc.select((beseMesh+'_cutterGrp'),d=True)
            oldCutterList = mc.ls(sl=1,fl=1,type='transform')
            initalIndex = len(existCutterList) + 2
            for o in oldCutterList:
                newName = ('bakeCutter' + str(initalIndex))
                mc.rename(o, newName)
                initalIndex += 1
            newList= mc.ls(sl=1,fl=1,type='transform')
            if len(newList)>0:
                mc.parent(newList,(beseMesh +'_bakeStep'))
    
            #unlock connection
            shape = mc.listRelatives(beseMesh, shapes=True,f=True)
            checkConnection = mc.listConnections((shape[0]+'.drawOverride'),c=1,p=1)
            if checkConnection != None:
                mc.disconnectAttr(checkConnection[1],checkConnection[0])
    
            #recreate bool
            recreateBool()
            mc.move(mirrorPivot[0],mirrorPivot[1],mirrorPivot[2], (beseMesh + ".scalePivot"),(beseMesh + ".rotatePivot"), absolute=True)
    
            if mode == 'unselect':
                #reconnect selected Cutters
                tempLong = []
                for c in cleanList:
                    longName = c.replace('_cutterGrp','_tempStoreGrp')
                    tempLong.append(longName)
                cleanList = tempLong    
                newCutterList = []
                for c in cleanList:
                    mc.select(c)
                    fixBoolNodeConnection()
                    newC = mc.ls(sl=1)
                    newCutterList.append(newC[0])
    
                mc.parent(newCutterList , (beseMesh +'_cutterGrp'))
                if mc.objExists((beseMesh +'_tempStoreGrp')):
                    mc.delete((beseMesh +'_tempStoreGrp'))
    
            setCutterBaseMesh()
            if mode == 'unselect':
                mc.select(selectedCutter)
    
            #restore symmetry
            if not mc.attributeQuery('symmetryX', node = beseMesh, ex=True ):
                mc.addAttr(beseMesh, ln='symmetryX', at = "long" )
                mc.setAttr((beseMesh+'.symmetryX'),getSymX)
            if not mc.attributeQuery('symmetryY', node = beseMesh, ex=True ):
                mc.addAttr(beseMesh, ln='symmetryY', at = "long" )
                mc.setAttr((beseMesh+'.symmetryY'),getSymY)
            if not mc.attributeQuery('symmetryZ', node = beseMesh, ex=True ):
                mc.addAttr(beseMesh, ln='symmetryZ', at = "long" )
                mc.setAttr((beseMesh+'.symmetryZ'),getSymZ)
    
            #checkSymmetryState
            checkSymX =  mc.getAttr(beseMesh+'.symmetryX')
            checkSymY =  mc.getAttr(beseMesh+'.symmetryY')
            checkSymZ =  mc.getAttr(beseMesh+'.symmetryZ')
    
            if checkSymX == 1:
                boolSymmetry('x',1)
            elif checkSymX == -1:
                boolSymmetry('x',2)
    
            if checkSymY == 1:
                boolSymmetry('y',1)
            elif checkSymY == -1:
                boolSymmetry('y',2)
    
            if checkSymZ == 1:
                boolSymmetry('z',1)
            elif checkSymZ == -1:
                boolSymmetry('z',2)
    
            #hide all cage
            if mc.objExists(beseMesh + '_cageGrp'):
                mc.hide(beseMesh + '_cageGrp')
            #cageList = mc.ls((beseMesh + '_cage*'),type='transform')
            #for c in cageList:
            #    mc.setAttr((c+'.visibility'),0)
        mc.optionMenu('baseMeshMenu', e = True, value = beseMesh)
        restoreMissingGrps()

def hindOutlinerList():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        hideOutlinerList = ['_preSubBox','_preUnionBox','_myBoolUnion','_afterSubBox','_myBoolSub']
        for h in hideOutlinerList:
            mc.setAttr((beseMesh + h + '.hiddenInOutliner'),1)
        outliner_editor = 'outlinerPanel1'
        mc.outlinerEditor(outliner_editor, edit=True, refresh=True)

def restoreCutterWithSymmtry():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        #check current
        shapes = mc.listRelatives((beseMesh+'_bool'), shapes=True)
        shadeEng = mc.listConnections(shapes , type = 'shadingEngine')
        materials = mc.ls(mc.listConnections(shadeEng ), materials = True)
        checkX1 = mc.button('symmXButtonP', q=1 , bgc = 1)
        checkX2 = mc.button('symmXButtonN', q=1 , bgc = 1)
        checkY1 = mc.button('symmYButtonP', q=1 , bgc = 1)
        checkY2 = mc.button('symmYButtonN', q=1 , bgc = 1)
        checkZ1 = mc.button('symmZButtonP', q=1 , bgc = 1)
        checkZ2 = mc.button('symmZButtonN', q=1 , bgc = 1)
        restoreCutter()
        if checkX1[0]>0.29:
            boolSymmetry("x" ,1)
        if checkX2[0]>0.29:
            boolSymmetry("x" ,2)
        if checkY1[1]>0.29:
            boolSymmetry("y" ,1)
        if checkY2[1]>0.29:
            boolSymmetry("y" ,2)
        if checkZ1[2]>0.29:
            boolSymmetry("z" ,1)
        if checkZ2[2]>0.29:
            boolSymmetry("z" ,2)
        #resotre shader
        checkM = 0
        for m in materials:
            if m == (beseMesh+'_Shader'):
                checkM = 1
        if checkM == 1:
            mc.sets((beseMesh+'_bool'), e=True, forceElement = (beseMesh+'_ShaderSG'))
        else:
            mc.sets((beseMesh+'_bool'), e=True, forceElement = 'initialShadingGroup')
        hindOutlinerList()
    
def restoreCutter():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if mc.objExists((beseMesh +'_cutterGrp')) == 0:
            mc.CreateEmptyGroup()
            mc.rename((beseMesh +'_cutterGrp'))
            mc.parent((beseMesh +'_cutterGrp'),(beseMesh +'BoolGrp'))
    
        if mc.objExists((beseMesh +'_bool')) ==0:
            mc.polyCube(w = 0.01, h=0.01, d=0.01 ,sx =1 ,sy= 1, sz= 1)
            mc.rename(beseMesh +'_preSubBox')
            mc.polyCube(w = 0.01, h=0.01, d=0.01 ,sx =1 ,sy= 1, sz= 1)
            mc.rename(beseMesh +'_preUnionBox')
            unionNode = mc.polyCBoolOp(beseMesh, (beseMesh +'_preUnionBox') , op= 1, ch= 1, preserveColor= 0, classification= 1, name= (beseMesh +'_union'))
            mc.rename(unionNode[0],(beseMesh +'_myBoolUnion'))
            subNode= mc.polyCBoolOp((beseMesh +'_myBoolUnion'), (beseMesh +'_preSubBox') , op= 2, ch= 1, preserveColor= 0, classification= 1, name= (beseMesh +'_bool'))
            mc.rename(subNode[0],(beseMesh +'_bool'))
            boolNode = mc.listConnections(mc.listHistory((beseMesh +'_bool'),f=1,ac=1),type='polyCBoolOp')
            boolNode = set(boolNode)
    
            #hack it by check '_', this is used by other group
            listClean = []
            for b in boolNode:
                if '_' not in b:
                    listClean.append(b)
    
    
            if len(listClean) == 3:
                for l in listClean:
                    checkOp = mc.getAttr( l +'.operation')
                    if checkOp == 2:
                        if mc.objExists(beseMesh +'_mySubs'):
                            mc.rename(l,(beseMesh +'_myCut'))
                        else:
                            mc.rename(l,(beseMesh +'_mySubs'))
                    else:
                        mc.rename(l,(beseMesh +'_myUnion'))
    
            mc.setAttr((beseMesh + '.visibility'), 0)
            baseNodes = mc.listRelatives(beseMesh, ad = True, f = True)
            baseTransNode = mc.ls(baseNodes,type = 'transform')
            baseMeshNode = mc.ls(baseNodes,type = 'mesh')
            mc.setAttr((baseMeshNode[0]+'.intermediateObject'), 0)
            mc.parent(baseMeshNode[0],(beseMesh +'BoolGrp'))
            mc.delete(beseMesh)
            mc.rename(beseMesh)
    
        bakeCutter('all')
        mc.delete(beseMesh+'_bool')
        mc.delete(beseMesh)
        mc.parent((beseMesh +'_bakeBaseMesh'),  (beseMesh+'BoolGrp'))
        mc.rename((beseMesh +'_bakeBaseMesh'), beseMesh)
        baseShape = mc.listRelatives((beseMesh), shapes=True,f=True)
        checkAtt =  mc.getAttr(baseShape[0] + '.overrideShading')
        if checkAtt == 0:
            mc.setAttr((baseShape[0] + '.overrideShading'), 1)
        #recreate bool
        recreateBool()
        #restore cutters
        mc.select((beseMesh+'_bakeStep'), hi=True)
        mc.select((beseMesh+'_bakeStep'),d=True)
        restoreCutterList = mc.ls(sl=1,fl=1,type='transform')
        for r in restoreCutterList:
            shapeNode = mc.listRelatives(r, f = True, shapes=True)
            mc.setAttr( (shapeNode[0]+".overrideEnabled") , 1)
            mc.setAttr( (shapeNode[0]+".overrideShading") , 0)
            mc.setAttr( (shapeNode[0]+".castsShadows") , 0)
            mc.setAttr( (shapeNode[0]+".receiveShadows") , 0)
            mc.setAttr( (shapeNode[0]+".primaryVisibility") , 0)
            mc.setAttr( (shapeNode[0]+".visibleInReflections") , 0)
            mc.setAttr( (shapeNode[0]+".visibleInRefractions") , 0)
            mc.select(r)
            fixBoolNodeConnection()
            name = r.split('|')[-1]
            checkNumber = ''.join([n for n in name.split('|')[-1] if n.isdigit()])
            mc.rename(r ,('boxCutter' + str(checkNumber)))
    
        if mc.objExists((beseMesh +'_cutterGrp')):
            mc.delete(beseMesh +'_cutterGrp')
    
        mc.rename((beseMesh +'_bakeStep'),(beseMesh +'_cutterGrp'))
        mc.select(cl=True)
        showAllCutter()
        fixShadowLink()

def flattenAlllCutter():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        mc.select((beseMesh+'_cutterGrp'), hi=True)
        mc.select((beseMesh+'_cutterGrp'),d=True)
        if mc.objExists('bakeCutter*'):
            mc.select('bakeCutter*',d=True)
        selList = mc.ls(sl=1,fl=1,type='transform')
        if len(selList) > 1:
            #bake array
            for s in selList:
                if mc.objExists(s):
                    mc.select(s)
                    myType = checkInstType()
                    if myType[1] != 'new':
                        instBake()
                        newNode = mc.ls(sl=1,fl=1)
                        selList.append(newNode[0])

def freeResultMesh():
    checkBaseMeshList()
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, ils = True)
    if beseMesh[0] != 'NoBaseMeshMenu':

        state = mc.checkBox('finalAll', q =1 ,v=1)
        if state == 0:
            beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True) 
            if mc.objExists((beseMesh+'_Done')) == 0 :
                bakeCutter("all")
                resultMesh = beseMesh +'_bool'
                mc.select(resultMesh)
                mc.duplicate(rr=True)
                mc.rename(beseMesh+'_Done')
                newNode = mc.ls(sl=True,fl=True)
                shapeNew = mc.listRelatives(newNode[0], s=True )
                mc.parent(w=True)
                mc.layerButton((beseMesh +'_BoolResult'), e=True ,lv=0)
                mc.setAttr((beseMesh +'BoolGrp.visibility'),0)
                mc.disconnectAttr((beseMesh+'_BoolResult.drawInfo'), (shapeNew[0]+'.drawOverride'))
                mc.editDisplayLayerMembers('defaultLayer',newNode)
                mc.hide(beseMesh+'BoolGrp')
                mc.setAttr((beseMesh+'BoolGrp.active'), 0)
        else:
            collect = []
            for b in beseMesh:
                meshName = b.replace('Menu','')
                mc.optionMenu('baseMeshMenu', e = True, v = meshName)
                if mc.objExists((meshName+'_Done')) == 0 :
                    bakeCutter("all")
                    resultMesh = meshName +'_bool'
                    mc.select(resultMesh)
                    mc.duplicate(rr=True)
                    mc.rename(meshName+'_Done')
                    newNode = mc.ls(sl=True,fl=True)
                    shapeNew = mc.listRelatives(newNode[0], s=True )
                    mc.parent(w=True)
                    mc.layerButton((meshName + '_BoolResult'), e=True ,lv=0)
                    mc.setAttr((meshName + 'BoolGrp.visibility'),0)
                    mc.disconnectAttr((meshName + '_BoolResult.drawInfo'), (shapeNew[0]+'.drawOverride'))
                    mc.editDisplayLayerMembers('defaultLayer',newNode)
                    mc.hide(meshName + 'BoolGrp')
                    mc.setAttr((meshName + 'BoolGrp.active'), 0)
                    collect.append(meshName+'_Done')
            if collect:
                mc.select(collect)

def drawCurveNow():
    mc.snapMode(grid=1)
    mc.CVCurveTool()

def makeDrawBlock():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        curveSel = mc.ls(sl=1,fl=1)
        if len(curveSel) == 1 :
            mc.snapMode(grid=0)
            shapeNode = mc.listRelatives(curveSel[0], f = True, shapes=True)
            checkOpen = mc.getAttr(shapeNode[0]+'.form')
            if checkOpen == 0:
                mc.closeCurve( curveSel[0], ch=True, rpo=True )
    
            mc.select(curveSel)
            mc.duplicate()
            mc.group(w=True)
            mc.rename('tempMirrorGrp')
    
            mc.parent('tempMirrorGrp','lineDrawPlaneOffset')
            mc.FreezeTransformations()
            getPresize = mc.floatField( 'cuterPreSize' , q=1, value = True)
            setScale =   mc.floatSliderGrp('cutterScaleSlider', q=1, value = True)
            mc.setAttr('tempMirrorGrp.translateZ',(getPresize*setScale*0.5*-1))
    
            mc.Ungroup()
            mc.select(curveSel,add=1)
            mc.FreezeTransformations()
            curveSel = mc.ls(sl=1,fl=1)
            mc.select(curveSel)
            loftNode = mc.loft(ch =1, u=1, c= 0, ar= 1, d= 3, ss= 1, rn= 0, po =1, rsn= True)
            tessConnList = mc.listConnections(loftNode, type = 'nurbsTessellate')
    
            mc.setAttr((tessConnList[0]+'.polygonType'), 1)
            checkCurveType = mc.getAttr(curveSel[0]+'.degree')
            if checkCurveType > 1:
                mc.setAttr((tessConnList[0]+'.format'), 0)
            else:
                mc.setAttr((tessConnList[0]+'.format'), 2)
            mc.setAttr((tessConnList[0]+'.uNumber'), 1)
            mc.setAttr((tessConnList[0]+'.vNumber'), 1)
            mc.FillHole()
            mc.delete(curveSel)
            mc.rename('drawBlock')
            blockSel = mc.listRelatives(mc.listRelatives(f = True, shapes=True), parent=1 , f=1 )
            mc.CenterPivot()
            mc.polyMergeVertex(blockSel,d = 0.01, am= 1,ch=0)
            mc.polySetToFaceNormal()
            renew = mc.listRelatives(mc.listRelatives(f = True, shapes=True), parent=1 , f=1 )
            mc.DeleteHistory()
            #fix normal direction
            checkNormalMehs = mc.ls(sl=1,fl=1,l=1)
            mc.polyExtrudeFacet(constructionHistory = 1, keepFacesTogether= 1, ltz = 0.001)
            mc.polySeparate(checkNormalMehs,ch=0)
            testMesh = mc.ls(sl=1,fl=1)
    
            worldFaceA = mc.polyEvaluate(testMesh[0],wa=True)
            worldFaceB = mc.polyEvaluate(testMesh[1],wa=True)
            if worldFaceA > worldFaceB:
                mc.delete(testMesh[1])
            else:
                mc.delete(testMesh[0])
    
            mc.parent(w=True)
            mc.delete(checkNormalMehs[0])
            mc.rename('drawBlock1')
            newBlock = mc.ls(sl=1,fl=1)
            mc.select(newBlock[0])
    
            #remove unwant edgeLoop
            if checkCurveType > 1:
                mc.polySelectConstraint(m=3,t=0x0008,sz=3)
                mc.polySelectConstraint(disable =True)
                ngon = mc.ls(sl=1,fl=1)
                mc.select(ngon)
                mc.ConvertSelectionToEdges()
                hardEdge = mc.ls(sl=1,fl=1)
                mc.SelectEdgeRingSp()
                mc.select(hardEdge,d=1)
                mc.polyDelEdge(cv=1)
                mc.select(newBlock[0])
    
            mc.parent(newBlock[0],'drawPlaneGrp')
            mc.FreezeTransformations()
            mc.CenterPivot()
            mc.parent(newBlock[0],w=True)
            mc.DeleteHistory()
            mc.ScaleTool()



def removeGap():
    newCutter = mc.ls(sl=True,fl=True,type = 'transform')
    for n in newCutter:
        if 'boxCutter' in n:
            if 'ArrayGrp' in n:
                n = n.replace('ArrayGrp','')
            extrudeNode = mc.listConnections(mc.listHistory(n,ac=1),type='polyExtrudeFace')
            if extrudeNode != None:
                mc.delete(extrudeNode)
            mc.setAttr((n+'.statePanel'),0)
            mc.setAttr((n+'.preBevel'),1)


def makeGap():
    newCutter = mc.ls(sl=True,fl=True,type = 'transform')
    for n in newCutter:
        if 'boxCutter' in n:
            if 'ArrayGrp' in n:
                n = n.replace('ArrayGrp','')
            extrudeNode = mc.listConnections(mc.listHistory(n,ac=1),type='polyExtrudeFace')
            if extrudeNode != None:
                mc.delete(extrudeNode)
            gapV = []
            storeX = mc.getAttr( n + '.scaleX')
            gapV = mc.floatSliderGrp('gapSlider', q=True, v = True)
            if gapV < 0.01:
                gapV = 0.01
                mc.floatSliderGrp('gapSlider', e = True, v=0.01)
            mc.setAttr((n+'.panelGap'),gapV)
            mc.setAttr((n+'.intPanelGap'),gapV)
            mc.setAttr((n+'.intScaleX'),storeX)
            mc.select(n)
            extNode = mc.polyExtrudeFacet( constructionHistory=True, keepFacesTogether = True, smoothingAngle=30, tk = gapV )
            cmdText = (extNode[0] + '.thickness = ' + n + '.intScaleX/' +  n + '.scaleX*' + str(gapV) + '*' + n + '.panelGap/' +  n + '.intPanelGap')
            mc.expression( s = cmdText, o = extNode[0], ae = True, uc = all)
            mc.setAttr((n+'.statePanel'),1)
            mc.setAttr((n+'.preBevel'),0)
    mc.select(newCutter)

def hideAllCutter():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        getCutters = mc.ls((beseMesh+'_cutterGrp|boxCutter*'),type = 'transform',l=True)
        mc.hide(getCutters)
        cutGridReset()

def showLastCutter():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        currentOne = mc.ls(sl=True,fl=True)
        getCutters = mc.ls((beseMesh+'_cutterGrp|boxCutter*'),type = 'transform')
        checkVis = []
        if len(getCutters) > 0:
            for g in getCutters:
                checkme = mc.getAttr(g+'.visibility')
                if checkme == 1:
                   checkVis.append(g)
            if len(currentOne) > 0:
                checkCutter = []
                for c in currentOne:
                    if 'boxCutter' in c:
                        checkCutter.append(c)
                if len(checkCutter)>0:
                    checkSel = mc.getAttr(checkCutter[0]+'.visibility')
                    mc.hide(getCutters)
                    if checkSel == 0:
                        mc.setAttr((checkCutter[0]+'.visibility'), 1)
                    else:
                        if len(checkVis) > 1:
                            mc.select(checkCutter[0])
                            mc.showHidden(checkCutter[0])
                        elif len(checkVis) == 1:
                            preCutter = 0
                            for i in range(len(getCutters)):
                                if getCutters[i] == checkCutter[0]:
                                    preCutter = i - 1
                            mc.select(getCutters[preCutter])
                            mc.showHidden(getCutters[preCutter])
                        else:
                            mc.select(getCutters[-1])
                            mc.showHidden(getCutters[-1])
            else:
                mc.hide(getCutters)
                mc.select(getCutters[-1])
                mc.showHidden(getCutters[-1])
            mc.setAttr((beseMesh+'_cutterGrp.visibility'), 1)

def showAllCutter():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        getCutters = mc.ls((beseMesh+'_cutterGrp|boxCutter*'),type = 'transform',l=True)
        checkAllCutterGrps = mc.ls(('*_cutterGrp'),type = 'transform',l=True)
        mc.hide(checkAllCutterGrps)
        mc.showHidden(getCutters)
        if mc.objExists((beseMesh +'_cutterGrp')) == 0:
            mc.CreateEmptyGroup()
            mc.rename((beseMesh +'_cutterGrp'))
            mc.parent((beseMesh +'_cutterGrp'),(beseMesh +'BoolGrp'))
    
        mc.setAttr((beseMesh+'_cutterGrp.visibility'), 1)


def hideUnSelectedCutters():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        currentSel = mc.ls(sl= True)
        getCutters = mc.ls((beseMesh+'_cutterGrp|boxCutter*'),type = 'transform',l=True)
        checkVisList = []
        for g in getCutters:
            state = mc.getAttr(g+'.visibility')
            if state == 1:
                checkVisList.append(g)
        if len(checkVisList) == len(currentSel):
            showAllCutter()
        else:
            mc.hide(getCutters)
            mc.showHidden(currentSel)
        mc.select(currentSel)

def attributeGapSlider():
    newCutter = mc.ls(sl=True,fl=True,type = 'transform')
    checkSlider = mc.floatSliderGrp('gapSlider',q=True, v= True )
    if len(newCutter) > 0:
        for n in newCutter:
            if 'ArrayGrp' in n:
                 n = n.replace('ArrayGrp','')
            checkGap = mc.getAttr(n +'.statePanel')
            if checkGap == 1:
                mc.setAttr((n +'.panelGap'),checkSlider)

def attributeIntSlider(attributName):
    newCutter = mc.ls(sl=True,fl=True,type = 'transform')
    sliderName = (str(attributName)+'Slider')
    checkSlider = mc.intSliderGrp(sliderName,q=True, v= True )
    if len(newCutter) > 0:
        for n in newCutter:
            if 'ArrayGrp' in n:
                 n = n.replace('ArrayGrp','')
            bevelNode = mc.listConnections(mc.listHistory(n),type='polyBevel3')
            if bevelNode != None:
                mc.setAttr((bevelNode[0] +'.' + attributName),checkSlider)

def attributeFloatSlider(attributName):
    newCutter = mc.ls(sl=True,fl=True,type = 'transform')
    sliderName = (str(attributName)+'Slider')
    checkSlider = mc.floatSliderGrp(sliderName,q=True, v= True )
    if len(newCutter) > 0:
        for n in newCutter:
            if 'ArrayGrp' in n:
                 n = n.replace('ArrayGrp','')
            bevelNode = mc.listConnections(mc.listHistory(n),type='polyBevel3')
            if bevelNode != None:
                mc.setAttr((bevelNode[0] +'.' + attributName),checkSlider)


def cutterMirrorOver(direction):
    listSel = mc.ls(sl=True, fl=True ,l=True)
    if len(listSel) > 0 and 'boxCutter' in listSel[0] and 'ArrayGrp' not in listSel[0]:
        mc.duplicate(rr=True, un=True)
        mc.group()
        if mc.objExists('tempPivot'):
            mc.delete('tempPivot')
        mc.rename('tempPivot')
        beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
        meshCOORD = mc.objectCenter(beseMesh,gl=True)
        mc.xform(ws=True,  pivots =[meshCOORD[0],meshCOORD[1],meshCOORD[2]])

        if direction == 'x':
            mc.setAttr( ('tempPivot.scaleX'),-1)
        if direction == 'y':
            mc.setAttr( ('tempPivot.scaleY'),-1)
        if direction == 'z':
            mc.setAttr( ('tempPivot.scaleZ'),-1)
        mc.FreezeTransformations()

        mc.select(mc.listRelatives('tempPivot', c=True, f = True, typ='transform'))
        mc.select((beseMesh+'_cutterGrp'), add=True)
        mc.parent()
        listNew = mc.ls(sl=True, fl=True ,l=True)
        fixBoolNodeConnection()

        mc.delete('tempPivot')
        for s in listSel:
            mc.setAttr((s+'.visibility'),0)
        mc.select(listNew)

def cutterMirror(axis):
    newCutter = mc.ls(sl=True,fl=True,type = 'transform')
    dulCutter = []
    if len(newCutter) > 0:
        for n in newCutter:
            if 'Cutter' in n:
                mc.FreezeTransformations()
                bboxObj = mc.xform(n , q = True, ws =True, bb=True)

                mirrorMode = 0

                if axis == 'x' :
                    if bboxObj[3] > 0 and bboxObj[0] > 0:
                        mirrorMode = 1
                    elif  bboxObj[3] < 0 and bboxObj[0] < 0:
                        mirrorMode = 1

                elif axis == 'y' :
                    if bboxObj[4] > 0 and bboxObj[1] > 0:
                        mirrorMode = 1
                    elif  bboxObj[4] < 0 and bboxObj[1] < 0:
                        mirrorMode = 1

                elif axis == 'z' :
                    if bboxObj[5] > 0 and bboxObj[2] > 0:
                        mirrorMode = 1
                    elif  bboxObj[5] < 0 and bboxObj[2] < 0:
                        mirrorMode = 1

                if mirrorMode == 1:
                    mc.select(n)
                    cutterMirrorOver(axis)
                    newC = mc.ls(sl=1)
                    dulCutter.append(newC[0])
                else:

                    lengthObj = _bbox_diagonal(bboxObj)
                    closeRange = lengthObj / 100

                    bboxSel = mc.xform(n , q = True, ws =True, bb=True)
                    midX = (bboxSel[3]+bboxSel[0])/2
                    midY = (bboxSel[4]+bboxSel[1])/2
                    midZ = (bboxSel[5]+bboxSel[2])/2
                    inRangeCv = []
                    vNo = mc.polyEvaluate(n, v = True )
                    checkPoint = 0
                    if axis == 'x' :
                        checkPoint = 0
                    elif axis == 'y' :
                        checkPoint = 1
                    else:
                        checkPoint = 2
                    for i in range(vNo):
                        positionV = mc.pointPosition((n +'.vtx[' + str(i) + ']') , w = True)
                        length= math.sqrt(math.pow(positionV[checkPoint],2))
                        if length <= closeRange:
                           inRangeCv.append((n +'.vtx[' + str(i) + ']'))
                        mc.select(inRangeCv, r=True)

                    # push those point off center a bit then mirror cut
                    if axis == 'x' :
                        for n in inRangeCv:
                            posiV = mc.pointPosition(n , w = True)
                            if midX >= 0:
                                mc.move((closeRange * -1.5) , posiV[1], posiV[2], n ,absolute=1)
                            else:
                                mc.move( (closeRange * 1.5) , posiV[1], posiV[2], n ,absolute=1)
                        cutPlane= mc.polyCut(n, ws = True, cd = 'X' , df = True , ch =True)
                        mc.setAttr((cutPlane[0]+'.cutPlaneCenterX'), 0)
                        mc.setAttr((cutPlane[0]+'.cutPlaneCenterY'), 0)
                        mc.setAttr((cutPlane[0]+'.cutPlaneCenterZ'), 0)
                        if midX > 0:
                            mc.setAttr((cutPlane[0]+'.cutPlaneRotateY'), 90)
                            mc.polyMirrorFace(n,cutMesh =1, axis = 0, axisDirection = 1, mergeMode = 1, mergeThresholdType = 1, mergeThreshold =0.001, mirrorAxis = 0 ,mirrorPosition = 0 ,smoothingAngle= 30 ,flipUVs =0 ,ch = 0)
                        else:
                            mc.setAttr((cutPlane[0]+'.cutPlaneRotateY'), -90)
                            mc.polyMirrorFace(n,cutMesh =1, axis = 0, axisDirection = 0, mergeMode = 1, mergeThresholdType = 1, mergeThreshold =0.001, mirrorAxis = 0 ,mirrorPosition = 0 ,smoothingAngle= 30 ,flipUVs =0 ,ch = 0)

                    if axis == 'y' :
                        for n in inRangeCv:
                            posiV = mc.pointPosition(n , w = True)
                            if midY >= 0:
                                mc.move(posiV[0], (closeRange  * -1.5) , posiV[2], n ,absolute=1)
                            else:
                                mc.move(posiV[0], (closeRange  * 1.5) , posiV[2], n ,absolute=1)
                        cutPlane= mc.polyCut(n, ws = True, cd = 'Y' , df = True , ch =True)
                        mc.setAttr((cutPlane[0]+'.cutPlaneCenterX'), 0)
                        mc.setAttr((cutPlane[0]+'.cutPlaneCenterY'), 0)
                        mc.setAttr((cutPlane[0]+'.cutPlaneCenterZ'), 0)
                        if midY > 0:
                            mc.setAttr((cutPlane[0]+'.cutPlaneRotateX'), -90)
                            mc.polyMirrorFace(n,cutMesh =1, axis = 1, axisDirection = 1, mergeMode = 1, mergeThresholdType = 1, mergeThreshold =0.001, mirrorAxis = 0 ,mirrorPosition = 0 ,smoothingAngle= 30 ,flipUVs =0 ,ch = 0)
                        else:
                            mc.setAttr((cutPlane[0]+'.cutPlaneRotateX'), 90)
                            mc.polyMirrorFace(n,cutMesh =1, axis = 1, axisDirection = 0, mergeMode = 1, mergeThresholdType = 1, mergeThreshold =0.001, mirrorAxis = 0 ,mirrorPosition = 0 ,smoothingAngle= 30 ,flipUVs =0 ,ch = 0)

                    if axis == 'z' :
                        for n in inRangeCv:
                            posiV = mc.pointPosition(n , w = True)
                            if midZ >= 0:
                                mc.move(posiV[0], posiV[1],(closeRange  * -1.5), n ,absolute=1)
                            else:
                                mc.move(posiV[0], posiV[1],(closeRange  * 1.5), n ,absolute=1)
                        cutPlane= mc.polyCut(n, ws = True, cd = 'Z' , df = True , ch =True)
                        mc.setAttr((cutPlane[0]+'.cutPlaneCenterX'), 0)
                        mc.setAttr((cutPlane[0]+'.cutPlaneCenterY'), 0)
                        mc.setAttr((cutPlane[0]+'.cutPlaneCenterZ'), 0)
                        if midZ > 0:
                            mc.setAttr((cutPlane[0]+'.cutPlaneRotateY'), 0)
                            mc.polyMirrorFace(n,cutMesh =1, axis = 2, axisDirection = 1, mergeMode = 1, mergeThresholdType = 1, mergeThreshold =0.001, mirrorAxis = 0 ,mirrorPosition = 0 ,smoothingAngle= 30 ,flipUVs =0 ,ch = 0)
                        else:
                            mc.setAttr((cutPlane[0]+'.cutPlaneRotateY'), 180)
                            mc.polyMirrorFace(n,cutMesh =1, axis = 2, axisDirection = 0, mergeMode = 1, mergeThresholdType = 1, mergeThreshold =0.001, mirrorAxis = 0 ,mirrorPosition = 0 ,smoothingAngle= 30 ,flipUVs =0 ,ch = 0)
                    mc.select(n)
                    dulCutter.append(n)
                    mc.BakeNonDefHistory()
            mc.select(dulCutter)

def useOwnCutterShape():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        ownCutter = mc.ls(sl=True, fl=True ,l=True)
        restoreMissingGrps()
        o = ownCutter[0]
        if len(ownCutter) > 0:
            for o in ownCutter:
                if ('_cutterGrp') in o:
                    print ('shape already been used')
                else:
                    if mc.objExists(beseMesh + '_BoolResult') == 0:
                        restoreCutterWithSymmtry()
                    mc.select(o)
                    mc.parent(o,(beseMesh+'_cutterGrp'))
                    ownCutter = mc.ls(sl=True, fl=True ,l=True)
                    newNumber = nextCutterNumber()
                    newName = 'boxCutter'+str(newNumber)
                    mc.select(ownCutter)
                    mc.rename(newName)
                    newCutter = mc.ls(sl=True, fl=True)
                    shapeNode = mc.listRelatives(newCutter, f = True, shapes=True)
                    mc.setAttr( (shapeNode[0]+".overrideEnabled") , 1)
                    mc.setAttr( (shapeNode[0]+".overrideShading") , 0)
                    mc.setAttr( (shapeNode[0]+".castsShadows") , 0)
                    mc.setAttr( (shapeNode[0]+".receiveShadows") , 0)
                    mc.setAttr( (shapeNode[0]+".primaryVisibility") , 0)
                    mc.setAttr( (shapeNode[0]+".visibleInReflections") , 0)
                    mc.setAttr( (shapeNode[0]+".visibleInRefractions") , 0)
                    checkButtonStateList = ['subsButton','unionButton','cutButton']
                    getCurrentType = ''
                    for c in checkButtonStateList:
                        buttonState = mc.button( c ,q=1,  bgc = True )
                        if buttonState[1] > 0.4:
                            getCurrentType = c
                    setType = getCurrentType.replace('Button','')
                    if setType == 'subs':
                        mc.setAttr( (shapeNode[0]+'.overrideColor'), 28)
                    elif setType == 'union':
                        mc.setAttr( (shapeNode[0]+'.overrideColor'), 31)
                    else:
                        mc.setAttr( (shapeNode[0]+'.overrideColor'), 25)
                    mc.connectAttr( (shapeNode[0]+".worldMatrix[0]"), ((beseMesh +'_my' + setType.title() +'.inputMat['+str(newNumber)+']')),f=True)
                    mc.connectAttr( (shapeNode[0]+".outMesh"), ((beseMesh +'_my' + setType.title() + '.inputPoly['+str(newNumber)+']')),f=True)
    
                    if not mc.attributeQuery('cutterDir', node = newCutter[0], ex=True ):
                        mc.addAttr(newCutter[0], ln='cutterDir',  dt= 'string')
                    if not mc.attributeQuery('cutterType', node = newCutter[0], ex=True ):
                        mc.addAttr(newCutter[0], ln='cutterType',  dt= 'string')
                    mc.setAttr((newCutter[0]+'.cutterDir'),e=True, keyable=True)
                    mc.setAttr((newCutter[0]+'.cutterType'),e=True, keyable=True)
    
                    if not mc.attributeQuery('cutterOp', node = newCutter[0], ex=True ):
                        mc.addAttr(newCutter[0], ln='cutterOp',  dt= 'string')
                    mc.setAttr((newCutter[0]+'.cutterOp'),e=True, keyable=True)
                    mc.setAttr((newCutter[0]+'.cutterOp'),setType,type="string")
    
                    if not mc.attributeQuery('statePanel', node = newCutter[0], ex=True ):
                        mc.addAttr(newCutter[0], ln='statePanel', at = "float" )
                    if not mc.attributeQuery('panelGap', node = newCutter[0], ex=True ):
                        mc.addAttr(newCutter[0], ln='panelGap', at = "float" )
                    if not mc.attributeQuery('intPanelGap', node = newCutter[0], ex=True ):
                        mc.addAttr(newCutter[0], ln='intPanelGap', at = "float" )
                    if not mc.attributeQuery('intScaleX', node = newCutter[0], ex=True ):
                        mc.addAttr(newCutter[0], ln='intScaleX', at = "float" )
    
                    if not mc.attributeQuery('preBevel', node = newCutter[0], ex=True ):
                        mc.addAttr(newCutter[0], ln='preBevel', at = "float" )
    
                    mc.setAttr((newCutter[0]+'.statePanel'),0)
                    mc.setAttr((newCutter[0]+'.preBevel'),1)
                    mc.select(newCutter[0])
                    mc.setAttr((newCutter[0]+'.cutterType'),'custom' ,type="string")
        else:
            print ('nothing select!')


def cutterDulpicate():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    dulCutter = mc.ls(sl=True, fl=True , l=True)
    newCutterList = []
    if len(dulCutter) > 0:
        for d in dulCutter:
            checkParent = d.split('|')
            if len(checkParent)>2 and 'boxCutter' in d and 'cutterGrp' in d:
                newNumber = nextCutterNumber()
                newName = 'boxCutter'+str(newNumber)
                mc.select(d)
                mc.duplicate(rr = True, un=True)
                mc.rename(newName)
                newCutter = mc.ls(sl=True, fl=True)
                shapeNode = mc.listRelatives(newCutter[0], f = True, shapes=True)
                mc.setAttr( (shapeNode[0]+".overrideEnabled") , 1)
                mc.setAttr( (shapeNode[0]+".overrideShading") , 0)
                mc.setAttr( (shapeNode[0]+".castsShadows") , 0)
                mc.setAttr( (shapeNode[0]+".receiveShadows") , 0)
                mc.setAttr( (shapeNode[0]+".primaryVisibility") , 0)
                mc.setAttr( (shapeNode[0]+".visibleInReflections") , 0)
                mc.setAttr( (shapeNode[0]+".visibleInRefractions") , 0)
                boolNode = mc.listConnections(mc.listHistory((beseMesh +'_bool'),f=1),type='polyCBoolOp')
                if boolNode != None:
                    mc.connectAttr( (shapeNode[0]+".worldMatrix[0]"), ((boolNode[0]+'.inputMat['+str(newNumber)+']')),f=True)
                    mc.connectAttr( (shapeNode[0]+".outMesh"), ((boolNode[0]+'.inputPoly['+str(newNumber)+']')),f=True)
                    mc.select(newCutter[0])
                    fixBoolNodeConnection()
                    newCutterList.append(newCutter[0])
            else:
                print (d + 'is not a cutter!!')
        mc.select(newCutterList)
    else:
        print ('nothing selected!')


def QChangeCutterDir(dir):
    selObj = mc.ls(sl=1, fl=1,l=True, type='transform')
    if len(selObj) == 1:

        checkMasterDir = []
        checkMasterNumber = []
        checkMasterDis = []
        arraySample = []
        myType = checkInstType()
        if 'ArrayGrp' in selObj[0]:
            myType = checkInstType()
            arraySample = myType[0]
            if myType[1] != 'new':
                checkMasterDir = mc.getAttr(arraySample+'.arrayDirection')
                checkMasterNumber = mc.getAttr(arraySample+'.arrayNumber')
                checkMasterDis = mc.getAttr(arraySample+'.arrayOffset')
                checkMasterType = myType[1]
                if myType[1] == 'radial':
                    removeRadArray()
                else:
                    instRemove()
            selObj = mc.ls(sl=1, fl=1,l=True, type='transform')
        mc.setAttr((selObj[0]+'.rotateX'), 0)
        mc.setAttr((selObj[0]+'.rotateY'), 0)
        mc.setAttr((selObj[0]+'.rotateZ'), 0)
        cutterDirection = mc.getAttr(selObj[0]+'.cutterDir')

        if dir == 'X':
            dir = 'Z'
        elif dir == 'Y':
            pass
        else:
            dir = 'X'

        parnetGrp = mc.listRelatives(selObj[0], parent =1, f=1)
        mc.group(em=True, name = (selObj[0]+'_offset'),parent = parnetGrp[0])
        newNode = mc.ls(sl=True,fl=True)
        mc.FreezeTransformations()
        sourcePivot = mc.xform(selObj[0], q=1, ws=1 ,rp=1)
        mc.xform(newNode ,ws=1, piv = (sourcePivot[0],sourcePivot[1],sourcePivot[2]))
        mc.parent(selObj[0],newNode)
        mc.setAttr((newNode[0]+'.rotate' + dir), 90)
        newNode = mc.ls(sl=True,fl=True)
        parnetGrpRemove = mc.listRelatives(newNode[0], parent =1, f=1)
        mc.parent(newNode[0],parnetGrp)
        mc.delete(parnetGrpRemove)
        newNode = mc.ls(sl=True,fl=True)
        if myType[1] != 'new':
            if myType[1] == 'radial':
                instRadAdd(checkMasterDir)
            else:
                instLinearAdd(checkMasterDir)
            mc.setAttr((newNode[0]+'.arrayNumber'),checkMasterNumber)
            mc.setAttr((newNode[0]+'.arrayOffset'),checkMasterDis)

def QBoxSmooth():
    newCutter = mc.ls(sl=True,fl=True,type = 'transform')
    if len(newCutter) > 0:
        for n in newCutter:
            if 'Cutter' in n:
                if 'ArrayGrp' in n:
                    myType = checkInstType()
                    n = (myType[0])
            #in case gap exist
            checkType = mc.getAttr(n + '.cutterType')
            extrudeNode = mc.listConnections(mc.listHistory(n,ac=1),type='polyExtrudeFace')
            if extrudeNode != None:
                mc.delete(extrudeNode)
            bevelNode = mc.listConnections(mc.listHistory(n,ac=1),type='polyBevel3')
            bevelType = []
            getFrac = []
            getSeg = []
            getDep = []
            mc.select(n)
            if bevelNode != None:
                mc.makeIdentity( n, apply=True, scale=True )
                #record old setting
                getFrac = mc.getAttr(bevelNode[0]+'.fraction')
                getSeg = mc.getAttr(bevelNode[0]+'.segments')
                getDep = mc.getAttr(bevelNode[0]+'.depth')
                mc.delete(bevelNode)
                mc.DeleteHistory()
            bevelNodeNew = mc.polyBevel3(n, mv = 1, mvt =0.001, fn = 1, fraction = 0.5, offsetAsFraction = 1, autoFit = 1, depth = 1, mitering = 0, miterAlong = 0, chamfer = 1,  segments = 5,  ch = 1)
            mc.floatSliderGrp('fractionSlider', e=True , v = 0.5)
            mc.intSliderGrp('segmentsSlider',   e=True , v = 5)
            mc.floatSliderGrp('depthSlider',    e=True , v = 1)
            if bevelNode != None:
                mc.setAttr((bevelNodeNew[0]+'.fraction'),getFrac)
                mc.setAttr((bevelNodeNew[0]+'.segments'),getSeg)
                mc.setAttr((bevelNodeNew[0]+'.depth'),getDep)
                mc.floatSliderGrp('fractionSlider', e=True , v = getFrac)
                mc.intSliderGrp('segmentsSlider',   e=True , v = getSeg)
                mc.floatSliderGrp('depthSlider',    e=True , v = getDep)
            if checkType == 'corner' :
                mc.setAttr((n+'.cutterType'),'cmooth',type="string")
            else:
                mc.setAttr((n+'.cutterType'),'smooth',type="string")
            checkGapState = mc.getAttr(n+'.statePanel')
            if checkGapState == 1:
                mc.select(n)
                makeGap()
        mc.select(newCutter)

def QBoxBevel():
    newCutter = mc.ls(sl=True,fl=True,type = 'transform')
    if len(newCutter) > 0:
        for n in newCutter:
            if 'Cutter' in n:
                if 'ArrayGrp' in n:
                    myType = checkInstType()
                    n = (myType[0])
            #in case gap exist
            extrudeNode = mc.listConnections(mc.listHistory(n,ac=1),type='polyExtrudeFace',s=True)
            if extrudeNode != None:
                mc.delete(extrudeNode)
            bevelNode = mc.listConnections(mc.listHistory(n,ac=1),type='polyBevel3')
            bevelList = []
            bevelType = []
            getFrac = []
            getSeg = []
            getDep = []
            mc.select(n)
            mc.makeIdentity( n, apply=True, scale=True )
            if bevelNode != None:
                #record old setting
                getFrac = mc.getAttr(bevelNode[0]+'.fraction')
                getSeg = mc.getAttr(bevelNode[0]+'.segments')
                getDep = mc.getAttr(bevelNode[0]+'.depth')
                mc.delete(bevelNode)
                mc.DeleteHistory()
            checkType = mc.getAttr(n + '.cutterType')
            if checkType == 'corner' or checkType == 'cmooth':
                bevelList = str(n + '.e[3]')
            else:   
                mc.select(n)
                mc.polySelectConstraint(mode = 3, type = 0x0008, size=1)
                mc.polySelectConstraint(disable =True)
                triFind = mc.ls(sl=1,fl=1)
                mc.select(n)
                mc.polySelectConstraint(mode = 3, type = 0x0008, size=3)
                mc.polySelectConstraint(disable =True)
                ngonFind = mc.ls(sl=1,fl=1)
                if len(triFind) == 2 and len(ngonFind) == 0:# case is triprism
                    bevelList = str(n + '.e[6:8]')
                elif len(triFind) > 0 or len(ngonFind) > 0:
                    if len(triFind) > 0:
                        mc.select(triFind)
                        mc.InvertSelection()#added - usless
                    else:
                        mc.select(ngonFind)
                    mc.select(n)
                    mc.ConvertSelectionToFaces()
                    mc.select(ngonFind,d=True)
                    mc.ConvertSelectionToContainedEdges()
                    bevelList = mc.ls(sl=1,fl=1)
                else:#case is cube
                    checkNoCustom = mc.getAttr(n+'.cutterType')
                    if checkNoCustom == 'custom':
                        mc.select(str(n + '.e[4:5]'))
                        mc.SelectEdgeRingSp()
                        bevelList = mc.ls(sl=1,fl=1)
                    else:
                        bevelList = str(n + '.e[8:11]')
                mc.setAttr((n+'.cutterType'),'bevel',type="string")

            bevelNodeNew = mc.polyBevel3(bevelList, mv = 1, mvt =0.001, fn = 1, fraction = 0.5, offsetAsFraction = 1, autoFit = 1, depth = 1, mitering = 0, miterAlong = 0, chamfer = 1,  segments = 5,  ch = 1)
            mc.floatSliderGrp('fractionSlider', e=True , v = 0.5)
            mc.intSliderGrp('segmentsSlider',   e=True , v = 5)
            mc.floatSliderGrp('depthSlider',    e=True , v = 1)
            if bevelNode != None:
                mc.setAttr((bevelNodeNew[0]+'.fraction'),getFrac)
                mc.setAttr((bevelNodeNew[0]+'.segments'),getSeg)
                mc.setAttr((bevelNodeNew[0]+'.depth'),getDep)
                mc.floatSliderGrp('fractionSlider', e=True , v = getFrac)
                mc.intSliderGrp('segmentsSlider',   e=True , v = getSeg)
                mc.floatSliderGrp('depthSlider',    e=True , v = getDep)
            if extrudeNode != None:
                makeGap()
            
            checkGapState = mc.getAttr(n+'.statePanel')
            if checkGapState == 1:
                mc.select(n)
                makeGap()
        mc.select(newCutter)

    else:
        anySel = mc.ls(sl=1)
        if anySel:
            mc.ConvertSelectionToEdges()
            selEdges =mc.filterExpand(ex =1, sm =32)
            if len(selEdges)>0:
                geoList = mc.ls(hl=1)
                for g in geoList:
                    checkType = mc.getAttr(g + '.cutterType')
                    if checkType == 'corner' :
                        checkEdge = str(g + '.e[3]')
                        bevelNodeNew = mc.polyBevel3(checkEdge, mv = 1, mvt =0.001, fn = 1, fraction = 0.5, offsetAsFraction = 1, autoFit = 1, depth = 1, mitering = 0, miterAlong = 0, chamfer = 1,  segments = 5,  ch = 1)
                    else:
                        mc.setAttr((g+'.cutterType'),'bevel',type="string")
                        checkEdge = []
                        for s in selEdges:
                            if g in s:
                                checkEdge.append(s)
                        mc.makeIdentity( g, apply=True, scale=True )
                        bevelNodeNew = mc.polyBevel3(checkEdge, mv = 1, mvt =0.001, fn = 1, fraction = 0.5, offsetAsFraction = 1, autoFit = 1, depth = 1, mitering = 0, miterAlong = 0, chamfer = 1,  segments = 5,  ch = 1)
            mc.select(geoList)
            mc.floatSliderGrp('fractionSlider', e=True , v = 0.5)
            mc.intSliderGrp('segmentsSlider',   e=True , v = 5)
            mc.floatSliderGrp('depthSlider',    e=True , v = 1)
        

def QBoxBevelRemove():
    newCutter = mc.ls(sl=True,fl=True,type = 'transform')
    if len(newCutter) > 0:
        for n in newCutter:
            if 'Cutter' in n:
                if 'ArrayGrp' in n:
                    myType = checkInstType()
                    n = (myType[0])
                checkNoCustom = mc.getAttr(n+'.cutterType')
                if checkNoCustom != 'custom':
                    mc.makeIdentity( n, apply=True, scale=True )
                    shapeNode = mc.listRelatives(n, f = True, shapes=True)
                    bevelNode = mc.listConnections(mc.listHistory(shapeNode,ac=1),type='polyBevel3')
                    if bevelNode != None:
                        checkGapState = mc.getAttr(n+'.statePanel')
                        if checkGapState == 1:
                            extrudeNode = mc.listConnections(mc.listHistory(n,ac=1),type='polyExtrudeFace')
                            if extrudeNode != None:
                                mc.delete(extrudeNode)
                        mc.delete(bevelNode)
                    mc.select(n)
                    mc.DeleteHistory()
                    if checkNoCustom == 'corner' or checkNoCustom == 'cmooth':
                        mc.setAttr((n+'.cutterType'),'corner',type="string")
                    else:
                        mc.setAttr((n+'.cutterType'),'none',type="string")
                    checkGapState = mc.getAttr(n+'.statePanel')
                    if checkGapState == 1:
                        mc.select(n)
                        makeGap()
        mc.select(newCutter)

def scrapeCutter():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    selCutter = mc.ls(sl=1, fl=1, type='transform')
    myType = checkInstType()
    if len(selCutter) == 1 and 'boxCutter' in selCutter[0] and  myType[1] == 'new':
        shapeNode = mc.listRelatives(selCutter[0], f = True, shapes=True)
        checkConnection = mc.listConnections(shapeNode[0]+'.worldMatrix',d=1,p=1)
        mc.disconnectAttr((shapeNode[0]+'.worldMatrix'), checkConnection[0])
        checkConnection = mc.listConnections(shapeNode[0]+'.outMesh',d=1,p=1)
        mc.disconnectAttr((shapeNode[0]+'.outMesh'), checkConnection[0])

        newNode = mc.duplicate((beseMesh+'_bool'),rr=1)
        mc.polyExtrudeFacet(newNode,constructionHistory = 1, keepFacesTogether= 1, tk = 0.1)
        mc.polySeparate(newNode, ch=0)
        testMesh = mc.ls(sl=1,fl=1)
        worldFaceA = mc.polyEvaluate(testMesh[0],wa=True)
        worldFaceB = mc.polyEvaluate(testMesh[1],wa=True)

        if worldFaceA > worldFaceB:
            mc.delete(testMesh[1])
        else:
            mc.delete(testMesh[0])
        mc.rename(selCutter[0] + '_skinMesh')

        if mc.objExists(selCutter[0] + 'skinGrp') == 0:
            mc.CreateEmptyGroup()
            mc.rename(selCutter[0] +'skinGrp')

        mc.parent((selCutter[0] + '_skinMesh'),(selCutter[0] +'skinGrp'))
        mc.delete(newNode)
        mc.ReversePolygonNormals()
        mc.DeleteHistory()


        #create intersection boolean
        subNode= mc.polyCBoolOp(selCutter[0],(selCutter[0] + '_skinMesh') , op= 3, ch= 1, preserveColor= 0, classification= 1, name= 'skinCutter')
        mc.DeleteHistory()

        #add cutter back
        extNode = mc.polyExtrudeFacet( constructionHistory=True, keepFacesTogether = True, smoothingAngle=30, tk = 1 )
        if mc.objExists((beseMesh +'_cutterGrp')) == 0:
            mc.CreateEmptyGroup()
            mc.rename((beseMesh +'_cutterGrp'))
            mc.parent((beseMesh +'_cutterGrp'),(beseMesh +'BoolGrp'))

        mc.select('skinCutter')
        useOwnCutterShape()
        #add skin attribute
        selCutter = mc.ls(sl=1, fl=1, type='transform')
        if not mc.attributeQuery('skinOffset', node = selCutter[0], ex=True ):
            mc.addAttr(selCutter[0], ln='skinOffset', at = "float" )
            mc.setAttr((selCutter[0]+'.skinOffset'),0.5)

        mc.setAttr((selCutter[0]+'.cutterType'),'scrape',type="string")
        mc.connectAttr((selCutter[0] +'.skinOffset'), (extNode[0] +'.thickness'),f=True)
        #link slider
        mc.connectControl('scrapeSlider', (selCutter[0] +'.skinOffset'))

def addBevelDirectionAttr():
    newCutter = mc.ls(sl=True, fl=True)
    mc.setAttr((newCutter[0]+'.cutterDir'),'x',type="string")
    mc.setAttr((newCutter[0]+'.cutterType'),'bevel',type="string")

def offPressCutter():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        checkNoSnapX = mc.getAttr('sampleLoc.translateX')
        checkNoSnapY = mc.getAttr('sampleLoc.translateY')
        checkNoSnapZ = mc.getAttr('sampleLoc.translateZ')
        if checkNoSnapX !=0 and  checkNoSnapY !=0 and  checkNoSnapZ !=0:
            mc.select('sampleLoc')
            mc.pickWalk(d='down')
            newCutter = mc.ls(sl=1,fl=1)
            mc.parent(newCutter,(beseMesh+'_cutterGrp'))
        if mc.objExists('sampleLoc*'):
            mc.delete('sampleLoc*')
        if mc.objExists('snapLive*'):
            mc.delete('snapLive*')
        mc.setToolTo('moveSuperContext')

def goPressCutter(boxSide):
    global currentScaleRecord
    global currentCutterName
    hideAllCutter()
    if mc.objExists('sampleLoc*'):
        mc.delete('sampleLoc*')
    if mc.objExists('snapLive*'):
        mc.delete('snapLive*')
    #create cutter
    sideNumber = boxSide
    preRotAngle = []
    if sideNumber == 3:
        preRotAngle = 60
    elif sideNumber == 4:
        preRotAngle = 45
    elif sideNumber == 5:
        preRotAngle = 72
    elif sideNumber == 6:
        preRotAngle = 30
    
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if mc.objExists(beseMesh + '_BoolResult') == 0:
            restoreCutterWithSymmtry()
        nextIndex = nextCutterNumber()
        member =mc.editDisplayLayerMembers((beseMesh+'_BoolResult'),q=True)
        snapMesh =[]
        if member != None:
            snapMesh = member[0]
        mc.setToolTo('moveSuperContext')
        getPresize = mc.floatField( 'cuterPreSize' , q=1, value = True)
        setScale =   mc.floatSliderGrp('cutterScaleSlider', q=1, value = True)
        mc.polyCylinder(r = getPresize, h= (1.5*getPresize) ,sx= boxSide, sy =0, sz=0, rcp= 0 , cuv =3 ,ch=1)
        mc.rename('boxCutter'+str(nextIndex))
        newCutter = mc.ls(sl=True, fl=True)
        currentCutterName = newCutter[0]
        mc.setAttr( (newCutter[0]+'.rotateY'), preRotAngle)
        mc.makeIdentity((newCutter[0]),apply =1, t = 0, r = 1, s =0, n =0, pn= 1)
        mc.setAttr( (newCutter[0]+'.scaleX'),(setScale))
        mc.setAttr( (newCutter[0]+'.scaleZ'),(setScale))
        mc.setAttr( (newCutter[0]+'.scaleY'),(setScale))
        currentScaleRecord = setScale
        #mc.CenterPivot()
        mc.group()
        mc.rename('sampleLoc')
        mc.xform(ws =True, piv =(0,0,0))
        mc.setAttr('sampleLoc.scaleX', 0.001)
        mc.setAttr('sampleLoc.scaleY', 0.001)
        mc.setAttr('sampleLoc.scaleZ', 0.001)
        refTopNode = mc.ls(sl = True,fl =True, type= 'transform')[0]
        transDownNode = mc.listRelatives('sampleLoc', c=True,f=True )
        #cutter in position
        #add attr
        shapeNode = mc.listRelatives(newCutter[0], shapes=True ,f =True)
        mc.setAttr( (shapeNode[0]+".overrideEnabled") , 1)
        mc.setAttr( (shapeNode[0]+".overrideShading") , 0)
        mc.setAttr( (shapeNode[0]+".castsShadows") , 0)
        mc.setAttr( (shapeNode[0]+".receiveShadows") , 0)
        mc.setAttr( (shapeNode[0]+".primaryVisibility") , 0)
        mc.setAttr( (shapeNode[0]+".visibleInReflections") , 0)
        mc.setAttr( (shapeNode[0]+".visibleInRefractions") , 0)
    
        if not mc.attributeQuery('cutterDir', node = newCutter[0], ex=True ):
            mc.addAttr(newCutter[0], ln='cutterDir',  dt= 'string')
        if not mc.attributeQuery('cutterType', node = newCutter[0], ex=True ):
            mc.addAttr(newCutter[0], ln='cutterType',  dt= 'string')
        mc.setAttr((newCutter[0]+'.cutterDir'),e=True, keyable=True)
        mc.setAttr((newCutter[0]+'.cutt erType'),e=True, keyable=True)
    
        if not mc.attributeQuery('cutterOp', node = newCutter[0], ex=True ):
            mc.addAttr(newCutter[0], ln='cutterOp',  dt= 'string')
        mc.setAttr((newCutter[0]+'.cutterOp'),e=True, keyable=True)
    
        checkButtonStateList = ['subsButton','unionButton','cutButton']
        getCurrentType = ''
        for c in checkButtonStateList:
            buttonState = mc.button( c ,q=1,  bgc = True )
            if buttonState[1] > 0.4:
                getCurrentType = c
        if getCurrentType == '':
            getCurrentType = 'subsButton'
            mc.button( 'subsButton' , e=1,  bgc = [0.3,0.5,0.6] )
        setType = getCurrentType.replace('Button','')
        mc.setAttr((newCutter[0]+'.cutterOp'),setType,type="string")
        if setType == 'subs':
            mc.setAttr( (shapeNode[0]+'.overrideColor'), 28)
        elif setType == 'union':
            mc.setAttr( (shapeNode[0]+'.overrideColor'), 31)
        else:
            mc.setAttr( (shapeNode[0]+'.overrideColor'), 25)
    
        if not mc.attributeQuery('statePanel', node = newCutter[0], ex=True ):
            mc.addAttr(newCutter[0], ln='statePanel', at = "float" )
        if not mc.attributeQuery('panelGap', node = newCutter[0], ex=True ):
            mc.addAttr(newCutter[0], ln='panelGap', at = "float" )
        if not mc.attributeQuery('intPanelGap', node = newCutter[0], ex=True ):
            mc.addAttr(newCutter[0], ln='intPanelGap', at = "float" )
        if not mc.attributeQuery('intScaleX', node = newCutter[0], ex=True ):
            mc.addAttr(newCutter[0], ln='intScaleX', at = "float" )
        if not mc.attributeQuery('preBevel', node = newCutter[0], ex=True ):
            mc.addAttr(newCutter[0], ln='preBevel', at = "float" )
        mc.setAttr((newCutter[0]+'.statePanel'),0)
        mc.setAttr((newCutter[0]+'.preBevel'),1)
        mc.select(('boxCutter'+str(nextIndex)))
        fixBoolNodeConnection()
        addBevelDirectionAttr()
        beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
        snapMesh = (beseMesh +'_bool')
        mc.duplicate(snapMesh,n='snapLive')
        mc.setAttr('snapLive.visibility',0)
        mc.select(cl=1)
        ##### undo ######
        global ctxCutter
        ctxCutter = 'ctxCutter'
        mc.intSliderGrp('cutterSideSlider', e=1,  v = boxSide)
        if mc.draggerContext(ctxCutter, exists=True):
            mc.deleteUI(ctxCutter)
        mc.draggerContext(ctxCutter, pressCommand = onPressCutter, rc = offPressCutter, dragCommand = onDragCutterCMD, name=ctxCutter, cursor='crossHair', undoMode='all')
        mc.setToolTo(ctxCutter)


def onDragCutterCMD():
    mc.undoInfo(swf=0)
    onDragCutter()
    mc.undoInfo(swf=1)

def onDragCutter():
    global ctxCutter
    global screenX,screenY
    global currentScaleRecord
    global currentCutterName
    selSample = 'sampleLoc'
    modifiers = mc.getModifiers()
    if (modifiers == 1):
        #print 'shift Press'
        vpX, vpY, _ = mc.draggerContext(ctxCutter, query=True, dragPoint=True)
        distanceA = (vpX - screenX)
        rotateRun = (distanceA) /4
        if rotateRun > 360 :
            rotateRun = 360
        elif rotateRun < -360 :
            rotateRun = -360

        mc.setAttr((currentCutterName + '.rotateY'),rotateRun)
        mc.refresh(cv=True,f=True)

    elif(modifiers == 4):
        #print 'ctrl selSample'
        vpX, vpY, _ = mc.draggerContext(ctxCutter, query=True, dragPoint=True)
        distanceB = vpX - screenX
        scaleCheck = distanceB / 100
        scaleRun = currentScaleRecord + scaleCheck
        if scaleRun > 5:
            scaleRun = 5
        elif scaleRun < 0:
            scaleRun = 0.1
        mc.floatSliderGrp('cutterScaleSlider',  e=1 ,v = scaleRun )
        mc.setAttr(('sampleLoc.scaleX'),scaleRun)
        mc.setAttr(('sampleLoc.scaleY'),scaleRun)
        mc.setAttr(('sampleLoc.scaleZ'),scaleRun)
        mc.refresh(cv=True,f=True)
    elif(modifiers == 8):
        vpX, vpY, _ = mc.draggerContext(ctxCutter, query=True, dragPoint=True)
        pos = om.MPoint()
        dir = om.MVector()
        hitpoint = om.MFloatPoint()
        omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
        pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
        #current camera
        view = omui.M3dView.active3dView()
        cam = om.MDagPath()
        view.getCamera(cam)
        camPath = cam.fullPathName()
        cameraTrans = mc.listRelatives(camPath,type='transform',p=True)
        cameraPosition = mc.xform(cameraTrans,q=1,ws=1,rp=1)
        checkHit = 0
        finalMesh = []
        finalX = 0
        finalY = 0
        finalZ = 0
        shortDistance = 10000000000
        distanceBetween = 1000000000
        meshNode = mc.listRelatives(selSample, fullPath=True ,ad=True)
        myShape = mc.listRelatives(meshNode, shapes=True,f=True)
        hitFacePtr = om.MScriptUtil().asIntPtr()
        hitFace = []
        beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
        member =mc.editDisplayLayerMembers((beseMesh+'_BoolResult'),q=True)
        snapMesh = (beseMesh +'_boolShape')
        checkList = []
        checkList.append('snapLive')
        for mesh in checkList:
            selectionList = om.MSelectionList()
            selectionList.add(mesh)
            dagPath = om.MDagPath()
            selectionList.getDagPath(0, dagPath)
            fnMesh = om.MFnMesh(dagPath)
            intersection = fnMesh.closestIntersection(
            om.MFloatPoint(pos2),
            om.MFloatVector(dir),
            None,
            None,
            False,
            om.MSpace.kWorld,
            99999,
            False,
            None,
            hitpoint,
            None,
            hitFacePtr,
            None,
            None,
            None)
            if intersection:
                x = hitpoint.x
                y = hitpoint.y
                z = hitpoint.z
                distanceBetween = math.sqrt( ((float(cameraPosition[0]) - x)**2)  + ((float(cameraPosition[1]) - y)**2) + ((float(cameraPosition[2]) - z)**2))
                if distanceBetween < shortDistance:
                    shortDistance = distanceBetween
                    finalMesh = mesh
                    hitFace = om.MScriptUtil(hitFacePtr).asInt()

                    hitFaceName = (mesh + '.f[' + str(hitFace) +']')

                cpX,cpY,cpZ = getPolyFaceCenter(hitFaceName)
                # bug, for some reason it doesn't like value is 0
                if cpX == 0:
                    cpX = 0.000001
                if cpY == 0:
                    cpY = 0.000001
                if cpZ == 0:
                    cpZ = 0.000001
                mc.setAttr(('sampleLoc.translateX'),cpX)
                mc.setAttr(('sampleLoc.translateY'),cpY)
                mc.setAttr(('sampleLoc.translateZ'),cpZ)
                mc.refresh(cv=True,f=True)
    else:
        vpX, vpY, _ = mc.draggerContext(ctxCutter, query=True, dragPoint=True)
        currentSX = vpX
        currentSY = vpY
        pos = om.MPoint()
        dir = om.MVector()
        hitpoint = om.MFloatPoint()
        omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
        pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
        #current camera
        view = omui.M3dView.active3dView()
        cam = om.MDagPath()
        view.getCamera(cam)
        camPath = cam.fullPathName()

        cameraTrans = mc.listRelatives(camPath,type='transform',p=True)
        cameraPosition = mc.xform(cameraTrans,q=1,ws=1,rp=1)

        checkHit = 0
        finalMesh = []
        finalX = 0
        finalY = 0
        finalZ = 0
        shortDistance = 10000000000
        distanceBetween = 1000000000
        meshNode = mc.listRelatives(selSample, fullPath=True ,ad=True)
        myShape = mc.listRelatives(meshNode, shapes=True,f=True)

        hitFacePtr = om.MScriptUtil().asIntPtr()
        hitFace = []
        beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
        member =mc.editDisplayLayerMembers((beseMesh+'_BoolResult'),q=True)
        snapMesh = (beseMesh +'_boolShape')
        checkList = []
        checkList.append('snapLive')
        for mesh in checkList:
            selectionList = om.MSelectionList()
            selectionList.add(mesh)
            dagPath = om.MDagPath()
            selectionList.getDagPath(0, dagPath)
            fnMesh = om.MFnMesh(dagPath)
            intersection = fnMesh.closestIntersection(
            om.MFloatPoint(pos2),
            om.MFloatVector(dir),
            None,
            None,
            False,
            om.MSpace.kWorld,
            99999,
            False,
            None,
            hitpoint,
            None,
            hitFacePtr,
            None,
            None,
            None)
            if intersection:
                x = hitpoint.x
                y = hitpoint.y
                z = hitpoint.z
                distanceBetween = math.sqrt( ((float(cameraPosition[0]) - x)**2)  + ((float(cameraPosition[1]) - y)**2) + ((float(cameraPosition[2]) - z)**2))
                if distanceBetween < shortDistance:
                    shortDistance = distanceBetween
                    finalMesh = mesh
                    hitFace = om.MScriptUtil(hitFacePtr).asInt()
                    finalX = x
                    finalY = y
                    finalZ = z
                # bug, for some reason it doesn't like value is 0
                if finalX == 0:
                    finalX = 0.000001
                if finalY == 0:
                    finalY = 0.000001
                if finalZ == 0:
                    finalZ = 0.000001
                mc.setAttr('sampleLoc.translateX', finalX)
                mc.setAttr('sampleLoc.translateY', finalY)
                mc.setAttr('sampleLoc.translateZ',finalZ)
                hitFaceName = (mesh + '.f[' + str(hitFace) +']')
                rx, ry, rz = getFaceAngle(hitFaceName)
                checkButtonStateList = ['surfOrientButton','objOrientButton', 'worldOrientButton']
                getCurrentOrient = ''
                for c in checkButtonStateList:
                    buttonState = mc.button( c ,q=1,  bgc = True )
                    if buttonState[1] > 0.4:
                        getCurrentOrient = c
                if getCurrentOrient == 'surfOrientButton':
                    mc.setAttr('sampleLoc.rotateX', rx)
                    mc.setAttr('sampleLoc.rotateY', ry)
                    mc.setAttr('sampleLoc.rotateZ', rz)
                elif getCurrentOrient == 'objOrientButton':
                    pass
                elif getCurrentOrient == 'worldOrientButton':
                    pass
                mc.select('sampleLoc')
                mc.refresh(cv=True,f=True)



def onPressCutter():
    global ctxCutter
    global screenX,screenY
    vpX, vpY, _ = mc.draggerContext(ctxCutter, query=True, anchorPoint=True)
    screenX = vpX
    screenY = vpY
    pos = om.MPoint()
    dir = om.MVector()
    hitpoint = om.MFloatPoint()
    omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
    pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
    #current camera
    view = omui.M3dView.active3dView()
    cam = om.MDagPath()
    view.getCamera(cam)
    camPath = cam.fullPathName()
    cameraTrans = mc.listRelatives(camPath,type='transform',p=True)
    cameraPosition = mc.xform(cameraTrans,q=1,ws=1,rp=1)
    checkHit = 0
    finalMesh = []
    finalX = []
    finalY = []
    finalZ = []
    shortDistance = 10000000000
    distanceBetween = 1000000000
    hitFacePtr = om.MScriptUtil().asIntPtr()
    hitFace = []
    checkList = []
    checkList.append('snapLive')
    for mesh in checkList:
        selectionList = om.MSelectionList()
        selectionList.add(mesh)
        dagPath = om.MDagPath()
        selectionList.getDagPath(0, dagPath)
        fnMesh = om.MFnMesh(dagPath)

        intersection = fnMesh.closestIntersection(
        om.MFloatPoint(pos2),
        om.MFloatVector(dir),
        None,
        None,
        False,
        om.MSpace.kWorld,
        99999,
        False,
        None,
        hitpoint,
        None,
        hitFacePtr,
        None,
        None,
        None)

        if intersection:
            x = hitpoint.x
            y = hitpoint.y
            z = hitpoint.z
            distanceBetween = math.sqrt( ((float(cameraPosition[0]) - x)**2)  + ((float(cameraPosition[1]) - y)**2) + ((float(cameraPosition[2]) - z)**2))
            if distanceBetween < shortDistance:
                shortDistance = distanceBetween
                finalMesh = mesh
                finalX = x
                finalY = y
                finalZ = z
                hitFace = om.MScriptUtil(hitFacePtr).asInt()
            mc.setAttr('sampleLoc.translateX', finalX)
            mc.setAttr('sampleLoc.translateY', finalY)
            mc.setAttr('sampleLoc.translateZ',finalZ)
            hitFaceName = (mesh + '.f[' + str(hitFace) +']')
            rx, ry, rz = getFaceAngle(hitFaceName)
            checkButtonStateList = ['surfOrientButton','objOrientButton', 'worldOrientButton']
            getCurrentOrient = ''
            for c in checkButtonStateList:
                buttonState = mc.button( c ,q=1,  bgc = True )
                if buttonState[1] > 0.4:
                    getCurrentOrient = c
            if getCurrentOrient == 'surfOrientButton': # orient to face
                mc.setAttr('sampleLoc.rotateX', rx)
                mc.setAttr('sampleLoc.rotateY', ry)
                mc.setAttr('sampleLoc.rotateZ', rz)
            elif getCurrentOrient == 'objOrientButton': # orient to target mesh orientation
                beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
                mc.setAttr('sampleLoc.rotateX', mc.getAttr(beseMesh+'.rotateX'))
                mc.setAttr('sampleLoc.rotateY', mc.getAttr(beseMesh+'.rotateY'))
                mc.setAttr('sampleLoc.rotateZ', mc.getAttr(beseMesh+'.rotateZ'))
            elif getCurrentOrient == 'worldOrientButton': # no rotation
                pass
            mc.setAttr('sampleLoc.scaleX', 1)
            mc.setAttr('sampleLoc.scaleY', 1)
            mc.setAttr('sampleLoc.scaleZ', 1)
            mc.select('sampleLoc')
            mc.refresh(cv=True,f=True)

def getFaceAngle(faceName):
    shapeNode = mc.listRelatives(faceName, fullPath=True, parent=True)
    transformNode = mc.listRelatives(shapeNode[0], fullPath=True, parent=True)
    matrix_values = mc.xform(transformNode, query=True, worldSpace=True, matrix=True)
    matrix_float = [float(x) for x in matrix_values]  # Convert to float
    matrix_list = [matrix_float[i:i + 4] for i in range(0, len(matrix_float), 4)]
    matrix_4x4 = om.MMatrix()
    om.MScriptUtil.createMatrixFromList(matrix_float, matrix_4x4)
    face_normals_text = mc.polyInfo(faceName, faceNormals=True)[0]
    face_normals = [float(digit) for digit in re.findall(r'-?\d*\.\d*', face_normals_text)]
    normal_vector = om.MVector(*face_normals) * matrix_4x4
    upvector = om.MVector(0, 1, 0)
    quat = om.MQuaternion(upvector, normal_vector)
    quatAsEuler = quat.asEulerRotation()
    rx, ry, rz = math.degrees(quatAsEuler.x), math.degrees(quatAsEuler.y), math.degrees(quatAsEuler.z)
    return rx, ry, rz


def reTarget():
    newTarget = mc.ls(sl=1,fl=1)
    if len(newTarget) == 1:
        beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)

        #record symmetry
        getSymX = 0
        getSymY = 0
        getSymZ = 0

        if mc.attributeQuery('symmetryX', node = beseMesh, ex=True ):
            getSymX =  mc.getAttr(beseMesh+'.symmetryX')
        if mc.attributeQuery('symmetryY', node = beseMesh, ex=True ):
            getSymY =  mc.getAttr(beseMesh+'.symmetryY')
        if mc.attributeQuery('symmetryZ', node = beseMesh, ex=True ):
            getSymZ =  mc.getAttr(beseMesh+'.symmetryZ')


        bakeCutter("all")
        mc.parent(newTarget, (beseMesh+'_bakeStep'))
        #mc.delete((beseMesh+'_bakeBaseMesh'))
        mc.rename((beseMesh+'_bakeBaseMesh'),(beseMesh+'_temp'))
        mc.parent((beseMesh+'_temp'),w=1)
        mc.rename(newTarget, (beseMesh+'_bakeBaseMesh'))
        mc.rename((beseMesh+'_temp'), (beseMesh+'_old'))
        restoreCutter()


        #apply to new target
        if not mc.attributeQuery('symmetryX', node = beseMesh, ex=True ):
            mc.addAttr(beseMesh, ln='symmetryX', at = "long" )
            mc.setAttr((beseMesh+'.symmetryX'),getSymX)
        if not mc.attributeQuery('symmetryY', node = beseMesh, ex=True ):
            mc.addAttr(beseMesh, ln='symmetryY', at = "long" )
            mc.setAttr((beseMesh+'.symmetryY'),getSymY)
        if not mc.attributeQuery('symmetryZ', node = beseMesh, ex=True ):
            mc.addAttr(beseMesh, ln='symmetryZ', at = "long" )
            mc.setAttr((beseMesh+'.symmetryZ'),getSymZ)

        #hide all cage
        cageList = mc.ls((beseMesh + '_cage*'),type='transform')
        for c in cageList:
            mc.setAttr((c+'.visibility'),0)

        #checkSymmetryState
        checkSymX =  mc.getAttr(beseMesh+'.symmetryX')
        checkSymY =  mc.getAttr(beseMesh+'.symmetryY')
        checkSymZ =  mc.getAttr(beseMesh+'.symmetryZ')

        if checkSymX == 1:
            boolSymmetry('x',1)
        elif checkSymX == -1:
            boolSymmetry('x',2)

        if checkSymY == 1:
            boolSymmetry('y',1)
        elif checkSymY == -1:
            boolSymmetry('y',2)

        if checkSymZ == 1:
            boolSymmetry('z',1)
        elif checkSymZ == -1:
            boolSymmetry('z',2)

def getPolyFaceCenter(faceName):
    meshFaceName = faceName.split('.')[0]
    findVtx = mc.polyInfo(faceName, fv=1)
    getNumber = []
    checkNumber = ((findVtx[0].split(':')[1]).split('\n')[0]).split(' ')
    for c in checkNumber:
        findNumber = ''.join([n for n in c.split('|')[-1] if n.isdigit()])
        if findNumber:
            getNumber.append(findNumber)
    centerX = 0
    centerY = 0
    centerZ = 0
    for g in getNumber:
        x,y,z = mc.pointPosition((meshFaceName + '.vtx['+g + ']'),w=1)
        centerX = centerX + x
        centerY = centerY + y
        centerZ = centerZ + z

    centerX = centerX/len(getNumber)
    centerY = centerY/len(getNumber)
    centerZ = centerZ/len(getNumber)
    return centerX,centerY,centerZ

def meshBBox():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh is not None:
        mesh = (beseMesh +'_bool')
        if mc.objExists(mesh):
            bbox= mc.xform(mesh, q=1, ws=1, bb=1)
            length = _bbox_diagonal(bbox)
            bestV = length / 10
            mc.floatField( 'cuterPreSize' , e=True ,value=bestV )
            loadSymmetryState()

def checkBaseMeshList():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, ils = True)
    # remove any item not exist in outliner
    if beseMesh is not None:
        for c in beseMesh:
            if not 'NoBaseMeshMenu' in c:
                meshName = c.replace('Menu','BoolGrp')
                if mc.objExists(meshName) == 0:
                    mc.deleteUI(c)
    # load any boolGrp existed in outliner
    beseMeshCheck = mc.ls('*BoolGrp',type='transform')
    if len(beseMeshCheck)>0:
        mc.optionMenu('baseMeshMenu', e=True, dai = True)
        for b in beseMeshCheck:
            state = mc.getAttr(b +'.active')#check group active
            removeGrp = b.replace('BoolGrp','')
            if state == 1:
                checkSelMesh = mc.menuItem((removeGrp +"Menu"), q=True, ex = True)
                if checkSelMesh == 0:
                    mc.menuItem((removeGrp +"Menu"), label = removeGrp ,p = 'baseMeshMenu')
    # remove noBaseMeshMenu if any boolGrp existed
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, ils = True)
    if beseMesh is not None:
        if len(beseMesh) > 1:
            checkNoBase = mc.menuItem('NoBaseMeshMenu', q=True, ex = True)
            if checkNoBase == 1:
                mc.deleteUI("NoBaseMeshMenu")
    else:
        mc.menuItem("NoBaseMeshMenu", label='No Base Mesh' ,p = 'baseMeshMenu')
    #load mesh size
    meshBBox()
    #remove empty display layer
    allLayers = mc.ls(type='displayLayer')
    for a in allLayers:
        if not 'defaultLayer' in a:
            members = mc.editDisplayLayerMembers(a,query=True)
            if members == None:
                mc.delete(a)

def updateSnapState():
        #check snap border state
    mc.makeLive( none=True )
    mc.manipMoveContext('Move',e=True, snapLivePoint= False)
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    mc.button('borderAlginButton',e=True, bgc =  [0.28,0.28,0.28])
    if mc.objExists(beseMesh +'_borderBoxGrp') and mc.objExists(beseMesh +'_borderBox'):
        mc.button('borderAlginButton',e=True, bgc =  [0.3,0.5,0.6])
        mc.makeLive(  beseMesh +'_borderBox' )
        mc.manipMoveContext('Move',e=True, snapLivePoint= True)

def restoreMissingGrps():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if mc.objExists((beseMesh +'_cutterGrp')) == 0:
            mc.CreateEmptyGroup()
            mc.rename((beseMesh +'_cutterGrp'))
            mc.parent((beseMesh +'_cutterGrp'),(beseMesh +'BoolGrp'))


def setCutterBaseMesh():
    global sceneSize    
    beseMesh = mc.ls(sl=True,fl=True,type='transform')
    if len(beseMesh) == 1:
        mc.delete(beseMesh[0],ch=1)
        bbox = mc.exactWorldBoundingBox(beseMesh)
        x_size = bbox[3] - bbox[0]
        y_size = bbox[4] - bbox[1]
        z_size = bbox[5] - bbox[2]
        longest = max(x_size, y_size, z_size)
        sceneSize = longest / 100000
        #mc.makeIdentity(beseMesh[0],apply= True, t= 1, r =1, s =1, n= 0,pn=1)
        mc.editDisplayLayerMembers('defaultLayer',beseMesh[0])
        topNode = mel.eval('rootOf '+beseMesh[0])
        meshName = []
        if 'BoolGrp' in topNode:
            removeGrp = topNode.replace('BoolGrp','')
            removeParent = removeGrp.replace('|','')
            meshName = removeParent
        else:
            meshName =  beseMesh[0]
        meshName = meshName.replace('|','')
        checkSelMesh = mc.menuItem((meshName +"Menu"), q=True, ex = True)
        if checkSelMesh == 0:
            mc.menuItem((meshName +"Menu"), label = meshName ,p = 'baseMeshMenu')
            #mc.optionMenu('baseMeshMenu|OptionMenu', q=True, v=True) # to get the name of the current value
            #mc.optionMenu('baseMeshMenu|OptionMenu', q=True, sl=True) # to get the current index
            #mc.optionMenu('baseMeshMenu|OptionMenu', e=True, sl = 3 )# to change the current value
            mc.optionMenu('baseMeshMenu', e=True, v = meshName )# to change the current value
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh != 'No Base Mesh':
        if mc.objExists(beseMesh):
            checkPivot = mc.xform(beseMesh, q =True, sp=True,ws=True)
            if mc.objExists((beseMesh +'_cutterGrp')) == 0:
                mc.CreateEmptyGroup()
                mc.rename((beseMesh +'_cutterGrp'))
            if mc.objExists((beseMesh +'BoolGrp')) == 0:
                mc.CreateEmptyGroup()
                mc.rename((beseMesh +'BoolGrp'))
            if mc.objExists((beseMesh +'_bool')) ==0:
                mc.polyCube(w = sceneSize, h= sceneSize, d= sceneSize ,sx =1 ,sy= 1, sz= 1)
                mc.rename(beseMesh +'_preSubBox')
                mc.polyCube(w = sceneSize, h= sceneSize, d= sceneSize ,sx =1 ,sy= 1, sz= 1)
                mc.rename(beseMesh +'_afterSubBox')
                mc.polyCube(w = sceneSize, h= sceneSize, d= sceneSize ,sx =1 ,sy= 1, sz= 1)
                mc.rename(beseMesh +'_preUnionBox')
                #move pre box to base mesh center prevent error
                bbox= mc.xform(beseMesh, q=1, ws=1, bb=1)
                bX = (bbox[3]-bbox[0])/2 + bbox[0]
                bY = (bbox[4]-bbox[1])/2 + bbox[1]
                bZ = (bbox[5]-bbox[2])/2 + bbox[2]
                attrList = ['translateX','translateY','translateZ']
                preBoxList = [(beseMesh +'_preSubBox'),(beseMesh +'_afterSubBox'),(beseMesh +'_preUnionBox')]
                posList = [bX,bY,bZ]
                for p in preBoxList:
                    for i in range(0,3):
                        mc.setAttr(( p + '.' + attrList[i]),posList[i])
                subNode= mc.polyCBoolOp((beseMesh ), (beseMesh +'_preSubBox') , op= 2, ch= 1, preserveColor= 0, classification= 1, name= (beseMesh +'_bool'))
                mc.rename(subNode[0],(beseMesh +'_myBoolSub'))
                unionNode = mc.polyCBoolOp((beseMesh +'_myBoolSub'), (beseMesh +'_preUnionBox') , op= 1, ch= 1, preserveColor= 0, classification= 1, name= (beseMesh +'_union'))
                mc.rename(unionNode[0],(beseMesh +'_myBoolUnion'))
                subNode= mc.polyCBoolOp((beseMesh +'_myBoolUnion'), (beseMesh +'_afterSubBox') , op= 2, ch= 1, preserveColor= 0, classification= 1, name= (beseMesh +'_bool'))
                mc.rename(subNode[0],(beseMesh +'_bool'))
                boolNode = mc.listConnections(mc.listHistory((beseMesh +'_bool'),f=1,ac=1),type='polyCBoolOp')
                boolNode = set(boolNode)
                #hack it by check '_', this is used by other group
                listClean = []
                for b in boolNode:
                    if '_' not in b:
                        listClean.append(b)

                for l in listClean:
                    checkNodeType = mc.nodeType(l)
                    if checkNodeType == 'polyCBoolOp':
                        checkOp = mc.getAttr( l +'.operation')
                        if checkOp == 2:
                            if mc.objExists(beseMesh +'_mySubs'):
                                mc.rename(l,(beseMesh +'_myCut'))
                            else:
                                mc.rename(l,(beseMesh +'_mySubs'))
                        else:
                            mc.rename(l,(beseMesh +'_myUnion'))

                baseNodes = mc.listRelatives(beseMesh, ad = True, f = True)
                baseTransNode = mc.ls(baseNodes,type = 'transform')
                baseMeshNode = mc.ls(baseNodes,type = 'mesh')
                mc.setAttr((baseMeshNode[0]+'.intermediateObject'), 0)
                mc.parent(baseMeshNode[0],(beseMesh +'BoolGrp'),s=True)
                mc.delete(beseMesh)
                mc.pickWalk(d='up')
                mc.rename(beseMesh)
                mc.setAttr((beseMesh + '.visibility'), 0)
            if not mc.objExists((beseMesh +'_BoolResult')):
                mc.createDisplayLayer(name = (beseMesh +'_BoolResult'))
            mc.editDisplayLayerMembers( (beseMesh +'_BoolResult'),(beseMesh +'_bool')) # store my selection into the display layer
            mc.setAttr((beseMesh +'_BoolResult.displayType'),2)

            checkList = ['_cutterGrp','_preSubBox','_preUnionBox','_myBoolUnion','_bool', '', '_afterSubBox','_myBoolSub' ]
            for c in checkList:
                checkGrp = mc.ls((beseMesh + c), l=True)
                if len(checkGrp)>0:
                    if 'BoolGrp' not in checkGrp[0]:
                        mc.parent(checkGrp[0],(beseMesh +'BoolGrp'))

            mc.select(cl=True)
            mc.setAttr((beseMesh +'BoolGrp.visibility'),1)
            mc.move(checkPivot[0],checkPivot[1],checkPivot[2], (beseMesh + ".scalePivot"),(beseMesh + ".rotatePivot"), absolute=True)
            
            if not mc.attributeQuery('active', node = (beseMesh +'BoolGrp'), ex=True ):
                mc.addAttr((beseMesh +'BoolGrp'), ln='active',at="long", dv=1)
                mc.setAttr((beseMesh +'BoolGrp.active'), e=True, keyable=True)

            mc.setAttr((beseMesh +'BoolGrp.active'),1)
            
            meshBBox()
            hindOutlinerList()

            
############################################################################

def cut2DGo():
    global oldShader
    global cameraTrans
    global clickNo
    clickNo = 0
    global fnMeshA
    global targetMmesh
    global cutToolID
    global cameraUsed 
    global storeOrtho
    global storeLongSide
    storeLongSide = 0
    global storeCutCircleR
    storeCutCircleR = 0.01
    global storeCutCircleS
    storeCutCircleS = 16
    global tempExtrudeCurveP 
    tempExtrudeCurveP = 0
    global cutType 
    cleanList = ('extudeCluster','tempExtrudeBlock','tempExtrudeCurve','cutBlockShader','blockFizMesh')
    for c in cleanList:
        if mc.objExists(c):
            mc.delete(c)
    if targetMmesh and  targetMmesh != 'No Base Mesh_bool':
        shape_nodes = mc.listRelatives(targetMmesh, shapes=True, fullPath=True)
        oldShader = mc.listConnections(shape_nodes, type='shadingEngine')[0]
        view = omui.M3dView.active3dView()
        cam = om.MDagPath()
        view.getCamera(cam)
        camPath = cam.fullPathName()
        cameraTrans = mc.listRelatives(camPath,type='transform',p=True)
        camPivot = mc.xform(cameraTrans, q=1, ws=1, rp=1)
        is_ortho = mc.camera(cameraTrans, query=True, orthographic=True)
        cameraUsed = cameraTrans[0]
        bbox = mc.exactWorldBoundingBox(targetMmesh)
        width = bbox[3] - bbox[0]
        height = bbox[4] - bbox[1]
        depth = bbox[5] - bbox[2]
        longest_edge = max(width, height, depth)
        storeLongSide = longest_edge
        if mc.objExists('instCutPlane') == 0 or cameraUsed == [] or is_ortho == 1:
            instCreateInfoPlane()
            cutGridUIConnect()
        if  is_ortho == 0 and  storeOrtho == 1:
            instCreateInfoPlane()
            cutGridUIConnect()
        storeOrtho = is_ortho
        mc.setAttr("cutGirdLine.lineColor",  1, 1, 0 , type="double3")
        model_panels = mc.getPanel(type='modelPanel')
        for m in model_panels:
            state = mc.isolateSelect(m, q=1, s =1)
            if state:
                mc.isolateSelect(m, addDagObject= 'instCutGrp' )
        
        if cutType == 1:
            points = [(0, 0, 0), (0, 0, 0), (0, 0, 0)]
            mesh = mc.polyCreateFacet(p=points, n='tempExtrudeBlock')
        elif cutType == 2:
            mc.polyPlane(w=0.01, h=0.01, sx=1, sy=1, axis=(0, 0, 1), ch=0,n='tempExtrudeBlock')
            mc.cluster('tempExtrudeBlock.vtx[2]',n='cutBoxMoveBase')
            mc.cluster('tempExtrudeBlock.vtx[3]',n='cutBoxMoveX')
            mc.cluster('tempExtrudeBlock.vtx[1]',n='cutBoxMove')
            mc.cluster('tempExtrudeBlock.vtx[0]',n='cutBoxMoveZ')
            mc.pointConstraint('cutBoxMoveHandle', 'cutBoxMoveXHandle', mo=True ,skip=['y','z'], w =1)
            mc.pointConstraint('cutBoxMoveHandle', 'cutBoxMoveZHandle', mo=True ,skip=['x','z'], w =1)
            mc.group('cutBoxMov*',n='cutBoxMoveGrp')
            mc.xform('cutBoxMoveGrp', ws=True, piv=[-0.005, 0.005, 0])
            mc.parent('cutBoxMoveGrp', 'instCutGrp')
            mc.setAttr("cutBoxMoveGrp.rotate",0,0,0)
            getZ = mc.getAttr('instCutPlane.translateZ')
            mc.setAttr("cutBoxMoveGrp.translateZ", getZ)
            mc.group(empty=1,n='cutBoxMoveA')
            mc.group(empty=1,n='cutBoxMoveB')
            posA = mc.pointPosition('tempExtrudeBlock.vtx[2]', w = True)
            posB = mc.pointPosition('tempExtrudeBlock.vtx[1]', w = True)
            mc.select('cutBoxMoveA*')
            mc.setAttr('cutBoxMoveA.translate',posA[0],posA[1],posA[2])
            mc.setAttr('cutBoxMoveB.translate',posB[0],posB[1],posB[2])
            mc.pointConstraint('cutBoxMoveA', 'cutBoxMoveGrp', mo=True , w =1)
            mc.pointConstraint('cutBoxMoveB', 'cutBoxMoveHandle', mo=True , w =1,skip=['z'])
            mc.parent('cutBoxMoveB' ,'cutBoxMoveA')
            mc.setAttr("cutBoxMoveGrp.visibility",0)
            mc.setAttr("tempExtrudeBlock.visibility",0)
            mc.setAttr("cutBoxMoveA.hiddenInOutliner",1)
        elif cutType == 3:
            hisNode = mc.polyCylinder(sc=0, r=1 ,h=0.001, sx=storeCutCircleS,sy=1,sz=0, axis=(0, 0, 1),rcp=0,createUVs=3,ch=1,n='tempExtrudeBlock')
            if is_ortho == 1:
                mc.setAttr('tempExtrudeBlock.scaleX',0.01*longest_edge)
                mc.setAttr('tempExtrudeBlock.scaleY',0.01*longest_edge)
            else:
                mc.setAttr('tempExtrudeBlock.scaleX',0.01*longest_edge)
                mc.setAttr('tempExtrudeBlock.scaleY',0.01*longest_edge)
            mc.setAttr('tempExtrudeBlock.scaleZ',0.01)
            mc.setAttr('tempExtrudeBlock.visibility', 0)
            mc.rename(hisNode[-1], 'cutCircleContral')
        else:
            mc.curve(d=3, p=[(0, 0, 0)])
            mc.rename('tempExtrudeCurve')
            mc.setAttr('tempExtrudeCurve.visibility', 0)
            points = [(0, 0, 0), (0, 0, 0), (0, 0, 0)]
            mesh = mc.polyCreateFacet(p=points, n='tempExtrudeBlock')
            mc.setAttr('tempExtrudeBlock.visibility', 0)
            mc.displaySmoothness('tempExtrudeCurve',divisionsU=3, divisionsV=3, pointsWire=16, pointsShaded=4, polygonObject=3)
            mc.setAttr("tempExtrudeCurveShape.dispCV",1)
        mc.setAttr('tempExtrudeBlock.hiddenInOutliner',1)
        if mc.objExists("cutBlockShader") == 0:
            shader=mc.shadingNode("surfaceShader", name = 'cutBlockShader',asShader=True)
            shading_group= mc.sets(name='cutBlockShaderSG',renderable=True,noSurfaceShader=True,empty=True)
            mc.connectAttr('cutBlockShader.outColor', 'cutBlockShaderSG.surfaceShader',f=1 )
            mc.setAttr("cutBlockShader.outColor", 0.65, 0, 0.85, type="double3")
            mc.setAttr("cutBlockShader.outTransparency", 0.85, 0.85, 0.85, type="double3")
        mc.select('tempExtrudeBlock')
        mc.setAttr("tempExtrudeBlockShape.receiveShadows",0)
        mc.setAttr("tempExtrudeBlockShape.castsShadows",0)
        mc.hyperShade(assign="cutBlockShader") 
        selectionList = om.MSelectionList()
        selectionList.add('instCutPlane')
        dagPath = om.MDagPath()
        selectionList.getDagPath(0, dagPath)
        fnMeshA = om.MFnMesh(dagPath)
        mc.select(cl=1)
        mc.select(targetMmesh)
        cutToolID = mc.scriptJob(runOnce=True, event=["SelectionChanged", cut2DGoLock])
        cutToolID = mc.scriptJob(runOnce=True, event=["ToolChanged", cut2DGoLock])
        resetPanelFocus()



def cut2DGoLock():  
    script_jobs = mc.scriptJob(listJobs=True)
    cleanIDList = ('cut2DGoLock')
    for c in cleanIDList:
        for job in script_jobs:
            if c in job:
                job_id = int(job.split(":")[0])
                mc.evalDeferred(lambda: mc.scriptJob(kill=job_id, force=True))
                #mc.scriptJob(kill=job_id, force=True)
                
    global cutType 
    if mc.objExists("cutBlockShader"):
        mc.setAttr("cutBlockShader.outColor", 0, 1, 0.2, type="double3")
    lockAttr = ('tx','ty','tz','rx','ry','rz','sx','sy','sz')
    for k in lockAttr:
        mc.setAttr((cameraTrans[0] + '.'  + k), lock=1)
    if mc.objExists("cutGirdLine"):
        mc.setAttr("cutGirdLine.lineColor",   0.25, 1, 1 , type="double3")
    if cutType == 1:
        global ctx
        ctx = 'drawBlock'
        if mc.draggerContext(ctx, exists=True):
            mc.deleteUI(ctx)
        mc.draggerContext(ctx, pressCommand = cutClick, rc = cutClean, dragCommand = cutDrag, name=ctx,fnz=cutEnd, cursor='crossHair',undoMode='step')
        mc.setToolTo(ctx)
        cutToolID = mc.scriptJob(runOnce=True, event=["ToolChanged", cutFiz])
    elif cutType == 2:
        mc.select('tempExtrudeBlock')
        global ctxBox
        ctxBox = 'drawBox'
        if mc.draggerContext(ctxBox, exists=True):
            mc.deleteUI(ctxBox)
        mc.draggerContext(ctxBox, pressCommand = cutBoxClick, dragCommand = cutBoxDrag, name=ctxBox,fnz=cutEnd, cursor='crossHair',undoMode='step')
        mc.setToolTo(ctxBox)
        cutToolID = mc.scriptJob(runOnce=True, event=["ToolChanged", cutFiz])
    elif cutType == 3:
        mc.select('tempExtrudeBlock')
        global ctxCircle
        ctxCircle = 'drawCircle'
        if mc.draggerContext(ctxCircle, exists=True):
            mc.deleteUI(ctxCircle)
        mc.draggerContext(ctxCircle, pressCommand = cutCircleClick, dragCommand = cutCircleDrag, name=ctxCircle,fnz=cutEnd, cursor='crossHair',undoMode='step')
        mc.setToolTo(ctxCircle)
        cutToolID = mc.scriptJob(runOnce=True, event=["ToolChanged", cutFiz])
    else:
        mc.select('tempExtrudeCurve')
        global ctxCurve
        ctxCurve = 'ctxCurve'
        if mc.draggerContext(ctxCurve, exists=True):
            mc.deleteUI(ctxCurve)
        mc.draggerContext(ctxCurve, pressCommand = cutCurveClick, dragCommand = cutCurveDrag, name=ctxCurve,fnz=cutEnd, cursor='crossHair',undoMode='step')
        mc.setToolTo(ctxCurve)
        cutToolID = mc.scriptJob(runOnce=True, event=["ToolChanged", SplitCurve])

def cutBoxClick():
    checCurrentkHUD =  mc.headsUpDisplay(lh=1)
    if checCurrentkHUD is not None:
        for t in checCurrentkHUD:
            if 'HUDBevelStep' in t:
                mc.headsUpDisplay(t, rem=1)
    global ctxBox
    global screenX,screenY
    global fnMeshA
    global cutBoxMidP
    cutBoxMidP = (0,0,0)
    global curBevelCount
    curBevelCount = 0
    global boxRotRecord
    boxRotRecord = 0
    cutPlane = mc.radioButtonGrp('cutPlane', q=1, sl=1)
    modifiers = mc.getModifiers()
    if(modifiers == 1):
        if mc.objExists('cutBoxMoveA'):
            mc.delete('tempExtrudeBlock', ch=1)
            mc.parent('tempExtrudeBlock','instCutPlane')
            mc.FreezeTransformations()
            mc.CenterPivot() 
            if mc.objExists('cutBoxMove*'):
                mc.delete('cutBoxMove*')
    elif(modifiers != 13):
        if(modifiers == 5):
            smoothALLCorner()
        else:
            if mc.objExists('cutBevel'):
                mc.delete('cutBevel')
                mc.delete('polyExtrudeEdge*')
            if mc.objExists('cutBoxMoveA') == 0:
                if mc.objExists('tempExtrudeBlock*'):
                    mc.delete('tempExtrudeBlock*')
                if cutPlane == 1:
                    mc.polyPlane(w=0.01, h=0.01, sx=1, sy=1, axis=(0, 0, 1), ch=0,n='tempExtrudeBlock')
                    mc.cluster('tempExtrudeBlock.vtx[2]',n='cutBoxMoveBase')
                    mc.cluster('tempExtrudeBlock.vtx[3]',n='cutBoxMoveX')
                    mc.cluster('tempExtrudeBlock.vtx[1]',n='cutBoxMove')
                    mc.cluster('tempExtrudeBlock.vtx[0]',n='cutBoxMoveZ')
                    mc.pointConstraint('cutBoxMoveHandle', 'cutBoxMoveXHandle', mo=True ,skip=['y','z'], w =1)
                    mc.pointConstraint('cutBoxMoveHandle', 'cutBoxMoveZHandle', mo=True ,skip=['x','z'], w =1)
                    mc.group('cutBoxMov*',n='cutBoxMoveGrp')
                    mc.xform('cutBoxMoveGrp', ws=True, piv=[-0.005, 0.005, 0])
                    mc.parent('cutBoxMoveGrp', 'instCutGrp')
                    mc.setAttr("cutBoxMoveGrp.rotate",0,0,0)
                    getZ = mc.getAttr('instCutPlane.translateZ')
                    mc.setAttr("cutBoxMoveGrp.translateZ", getZ)
                    mc.group(empty=1,n='cutBoxMoveA')
                    mc.group(empty=1,n='cutBoxMoveB')
                    posA = mc.pointPosition('tempExtrudeBlock.vtx[2]', w = True)
                    posB = mc.pointPosition('tempExtrudeBlock.vtx[1]', w = True)
                    mc.setAttr('cutBoxMoveA.translate',posA[0],posA[1],posA[2])
                    mc.setAttr('cutBoxMoveB.translate',posB[0],posB[1],posB[2])
                    mc.pointConstraint('cutBoxMoveA', 'cutBoxMoveGrp', mo=True , w =1)
                    mc.pointConstraint('cutBoxMoveB', 'cutBoxMoveHandle', mo=True , w =1,skip=['z'])
                else:
                    mc.polyPlane(w=0.1, h=0.1, sx=1, sy=1, axis=(0, 1, 0), ch=0,n='tempExtrudeBlock')
                    mc.cluster('tempExtrudeBlock.vtx[2]',n='cutBoxMoveBase')
                    mc.cluster('tempExtrudeBlock.vtx[3]',n='cutBoxMoveX')
                    mc.cluster('tempExtrudeBlock.vtx[1]',n='cutBoxMove')
                    mc.cluster('tempExtrudeBlock.vtx[0]',n='cutBoxMoveZ')
                    mc.pointConstraint('cutBoxMoveHandle', 'cutBoxMoveXHandle', mo=True ,skip=['y','z'], w =1)
                    mc.pointConstraint('cutBoxMoveHandle', 'cutBoxMoveZHandle', mo=True ,skip=['x','y'], w =1)
                    mc.group('cutBoxMov*',n='cutBoxMoveGrp')
                    mc.xform('cutBoxMoveGrp', ws=True, piv=[-0.05,0,-0.05])
                    mc.parent('cutBoxMoveGrp', 'instCutGrp')
                    mc.setAttr("cutBoxMoveGrp.rotate",0,0,0)
                    getZ = mc.getAttr('instCutPlane.translateZ')
                    mc.setAttr("cutBoxMoveGrp.translateZ", getZ)
                    mc.group(empty=1,n='cutBoxMoveA')
                    mc.group(empty=1,n='cutBoxMoveB')
                    posA = mc.pointPosition('tempExtrudeBlock.vtx[2]', w = True)
                    posB = mc.pointPosition('tempExtrudeBlock.vtx[1]', w = True)
                    mc.setAttr('cutBoxMoveA.translate',posA[0],posA[1],posA[2])
                    mc.setAttr('cutBoxMoveB.translate',posB[0],posB[1],posB[2])
                    mc.pointConstraint('cutBoxMoveA', 'cutBoxMoveGrp', mo=True , w =1)
                    mc.pointConstraint('cutBoxMoveB', 'cutBoxMoveHandle', mo=True , w =1,skip=['y'])
                mc.parent('cutBoxMoveB' ,'cutBoxMoveA')
                mc.setAttr("cutBoxMoveGrp.visibility",0)
                mc.setAttr("cutBoxMoveA.hiddenInOutliner",1)
                mc.select('tempExtrudeBlock')
                mc.hyperShade(assign="cutBlockShader") 
                mc.setAttr("tempExtrudeBlockShape.receiveShadows",0)
                mc.setAttr("tempExtrudeBlockShape.castsShadows",0)
            ##############################################################################################
            if cutPlane == 1:
                getRotZ = mc.getAttr('instCutPlane.rotateZ')
                mc.setAttr('cutBoxMoveGrp.rotateZ',getRotZ)
            elif cutPlane == 2:       
                getRotY = mc.getAttr('instCutPlane.rotateY')
                mc.setAttr('cutBoxMoveGrp.rotateY',getRotY)
            else:
                getRotZ = mc.getAttr('instCutPlane.rotateZ')
                mc.setAttr('cutBoxMoveGrp.rotateZ',getRotZ)
                mc.setAttr('cutBoxMoveGrp.rotateX',90)

            vpX, vpY, _ = mc.draggerContext(ctxBox, query=True, anchorPoint=True)
            screenX = vpX
            screenY = vpY
            pos = om.MPoint()
            dir = om.MVector()
            omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
            pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
            hitpoint = om.MFloatPoint()
            hitFace = om.MScriptUtil()
            hitFace.createFromInt(0)
            hitFacePtr = hitFace.asIntPtr()
            intersection = fnMeshA.closestIntersection(
            om.MFloatPoint(pos2),
            om.MFloatVector(dir),
            None,
            None,
            False,
            om.MSpace.kWorld,
            100000,
            False,
            None,
            hitpoint,
            None,
            hitFacePtr,
            None,
            None,
            None)
            if intersection:
                mc.setAttr('tempExtrudeBlock.visibility',1)
                if(modifiers == 4):
                    hitFace = om.MScriptUtil(hitFacePtr).asInt()
                    posNew = om2.MPoint(hitpoint.x, hitpoint.y, hitpoint.z) 
                    sel = om2.MSelectionList()
                    sel.add('instCutPlane')
                    fnMeshB = om2.MFnMesh(sel.getDagPath(0))
                    face_vertices = fnMeshB.getPolygonVertices(hitFace)  
                    vertex_distances = ((vertex, fnMeshB.getPoint(vertex, om2.MSpace.kWorld).distanceTo(posNew))for vertex in face_vertices)
                    lockGridID = min(vertex_distances, key=operator.itemgetter(1))[0]
                    posiV = mc.pointPosition('instCutPlane.vtx[' +  str(lockGridID)  + ']', w = True)
                    mc.move(posiV[0],posiV[1],posiV[2], 'cutBoxMoveA' , absolute=True, ws=1)
                    mc.move(posiV[0],posiV[1],posiV[2], 'cutBoxMoveB' , absolute=True, ws=1)
                else:
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'cutBoxMoveA' , absolute=True, ws=1)
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'cutBoxMoveB' , absolute=True, ws=1)
                mc.refresh(cv=True,f=True)
    else:
        if mc.objExists('cutBoxMoveA'):
            posA = mc.xform('cutBoxMoveA', query=True, translation=True, worldSpace=True)
            posB = mc.xform('cutBoxMoveB', query=True, translation=True, worldSpace=True)
            midPos = [(posA[0] + posB[0]) / 2, (posA[1] + posB[1]) / 2, (posA[2] + posB[2]) / 2]
            distX = midPos[0] - posA[0]
            distY = midPos[1] - posA[1]
            distZ = midPos[2] - posA[2]
            cutBoxMidP = (distX,distY,distZ)
        vpX, vpY, _ = mc.draggerContext(ctxBox, query=True, anchorPoint=True)
        screenX = vpX
        screenY = vpY
        pos = om.MPoint()
        dir = om.MVector()
        omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
        pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
        hitpoint = om.MFloatPoint()
        hitFace = om.MScriptUtil()
        hitFace.createFromInt(0)
        hitFacePtr = hitFace.asIntPtr()
        intersection = fnMeshA.closestIntersection(
        om.MFloatPoint(pos2),
        om.MFloatVector(dir),
        None,
        None,
        False,
        om.MSpace.kWorld,
        100000,
        False,
        None,
        hitpoint,
        None,
        hitFacePtr,
        None,
        None,
        None)
        if intersection:
            if mc.objExists('cutBoxMoveA'):
                mc.move((hitpoint.x - cutBoxMidP[0]), (hitpoint.y - cutBoxMidP[1]), (hitpoint.z - cutBoxMidP[2]) , 'cutBoxMoveA' , absolute=True, ws=1)
            else:
                mc.move((hitpoint.x - cutBoxMidP[0]), (hitpoint.y - cutBoxMidP[1]), (hitpoint.z - cutBoxMidP[2]) , 'tempExtrudeBlock' , absolute=True, ws=1)
            mc.refresh(cv=True,f=True)

def cutBoxDrag():
    modifiers = mc.getModifiers()
    global ctxBox
    global screenX,screenY
    global fnMeshA
    global curBevelCount
    global boxRotRecord
    global cutBoxMidP
    vpX, vpY, _ = mc.draggerContext(ctxBox, query=True, dragPoint=True)
    if(modifiers == 1):
        if screenX > vpX:
            boxRotRecord = boxRotRecord -1
        else:
            boxRotRecord = boxRotRecord + 1
        screenX = vpX
        mc.setAttr('tempExtrudeBlock.rotateZ',(boxRotRecord*2))
        mc.refresh(cv=True,f=True)     
    elif(modifiers != 13):
        if mc.objExists('cutBevel'):
            if screenX > vpX:
                curBevelCount = curBevelCount -1
            else:
                curBevelCount = curBevelCount + 1
            screenX = vpX
            
            if(modifiers == 4):
                fra = curBevelCount * 0.01
                if fra < 0.01:
                    fra = 0.01
                mc.setAttr('cutBevel.fraction',(fra))
            elif(modifiers == 5):
                seg = int(curBevelCount *0.2)
                if seg < 1:
                    seg = 1
                mc.setAttr('cutBevel.segments',(seg))
            mc.refresh(cv=True,f=True)
        else:
            screenX = vpX
            screenY = vpY
            pos = om.MPoint()
            dir = om.MVector()
            omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
            pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
            hitpoint = om.MFloatPoint()
            hitFace = om.MScriptUtil()
            hitFace.createFromInt(0)
            hitFacePtr = hitFace.asIntPtr()
            intersection = fnMeshA.closestIntersection(
            om.MFloatPoint(pos2),
            om.MFloatVector(dir),
            None,
            None,
            False,
            om.MSpace.kWorld,
            100000,
            False,
            None,
            hitpoint,
            None,
            hitFacePtr,
            None,
            None,
            None)
            if intersection:
                if(modifiers == 4):
                    hitFace = om.MScriptUtil(hitFacePtr).asInt()
                    posNew = om2.MPoint(hitpoint.x, hitpoint.y, hitpoint.z) 
                    sel = om2.MSelectionList()
                    sel.add('instCutPlane')
                    fnMeshB = om2.MFnMesh(sel.getDagPath(0))
                    face_vertices = fnMeshB.getPolygonVertices(hitFace)  
                    vertex_distances = ((vertex, fnMeshB.getPoint(vertex, om2.MSpace.kWorld).distanceTo(posNew))for vertex in face_vertices)
                    lockGridID = min(vertex_distances, key=operator.itemgetter(1))[0]
                    posiV = mc.pointPosition('instCutPlane.vtx[' +  str(lockGridID)  + ']', w = True)
                    mc.move(posiV[0],posiV[1],posiV[2], 'cutBoxMoveB' , absolute=True, ws=1)
                else:
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'cutBoxMoveB' , absolute=True, ws=1)
                mc.refresh(cv=True,f=True)
    else:
        screenX = vpX
        screenY = vpY
        pos = om.MPoint()
        dir = om.MVector()
        omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
        pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
        hitpoint = om.MFloatPoint()
        hitFace = om.MScriptUtil()
        hitFace.createFromInt(0)
        hitFacePtr = hitFace.asIntPtr()
        intersection = fnMeshA.closestIntersection(
        om.MFloatPoint(pos2),
        om.MFloatVector(dir),
        None,
        None,
        False,
        om.MSpace.kWorld,
        100000,
        False,
        None,
        hitpoint,
        None,
        hitFacePtr,
        None,
        None,
        None)
        if intersection:
            if mc.objExists('cutBoxMoveA'):
                mc.move((hitpoint.x - cutBoxMidP[0]), (hitpoint.y - cutBoxMidP[1]), (hitpoint.z - cutBoxMidP[2]) , 'cutBoxMoveA' , absolute=True, ws=1)
            else:
                mc.move((hitpoint.x - cutBoxMidP[0]), (hitpoint.y - cutBoxMidP[1]), (hitpoint.z - cutBoxMidP[2]) , 'tempExtrudeBlock' , absolute=True, ws=1)
            mc.refresh(cv=True,f=True)
                    
def orthoCam():
    cleanList = ('extudeCluster','tempExtrudeBlock','cutBlockShader','blockFizMesh')
    for c in cleanList:
        if mc.objExists(c):
            mc.delete(c)
    global fnMeshA
    global targetMmesh
    global cameraUsed
    global clickNo
    clickNo = 0
    global recordHitPoint
    if targetMmesh:
        if mc.objExists('instCutGrp') == 0:
            instCreateInfoPlane()
            cutGridUIConnect()
        mc.setAttr("cutGirdLine.lineColor", 1, 1, 0, type="double3")
        model_panels = mc.getPanel(type='modelPanel')
        for m in model_panels:
            state = mc.isolateSelect(m, q=1, s =1)
            if state:
                mc.isolateSelect(m, addDagObject= 'instCutGrp' )
        curPanel = mc.getPanel(wf=1)
        if not 'modelPanel' in curPanel:
            curPanel = 'modelPanel4'
        mc.modelEditor( curPanel,e=1, planes=1)
        curCam = mc.modelPanel(curPanel,q=1, cam=1)
        cameraPos = mc.xform(curCam,q=1,ws=1,t=1)
        orthoValue = mc.camera(curCam,q=1, o=1)
        planePos=[]
        if orthoValue ==0:
            camRot = mc.camera(curCam,q=1, rot=1)
            camRotFixed = []
            for i in range(2):
                camRotTemp = camRot[i] / 360
                intOfTemp = int(camRotTemp)
                rotOver = 360 * intOfTemp
                camRotFixed.append( camRot[i] - rotOver)
            for i in range(2):
                if camRotFixed[i] < 0 :
                      camRotFixed[i]= camRotFixed[i] +360;
            getCurrentCamera=[]
            if (camRotFixed[0] >= 45 and camRotFixed[0] < 135):
                getCurrentCamera = 'buttom'
            elif (camRotFixed[0] >= 225 and camRotFixed[0] < 315):
                getCurrentCamera = 'top'
            elif (camRotFixed[1] < 45):
                getCurrentCamera = 'front'
            elif (camRotFixed[1] >= 315 ):
                getCurrentCamera = 'front'
            elif (camRotFixed[1] >= 45 and camRotFixed[1] < 135):
                getCurrentCamera = 'right'
            elif (camRotFixed[1] >= 135 and camRotFixed[1] < 225):
                getCurrentCamera = 'back'
            elif (camRotFixed[1] >= 225 and camRotFixed[1] < 315):
                getCurrentCamera = 'left'
            if cameraUsed != getCurrentCamera:
                mc.setAttr("instCutGrp.rotateX", 0)
                mc.setAttr("instCutGrp.rotateY", 0)
                mc.setAttr("instCutGrp.rotateZ", 0)
                mesh = targetMmesh
                bbox= mc.xform(mesh, q=1, ws=1, bb=1)
                length = _bbox_diagonal(bbox)
                length = int(length *1.1 )
                meshCOORD = mc.objectCenter(mesh,gl=True)
                constructionPlanePos=[]
                if getCurrentCamera == 'front' or getCurrentCamera == 'back':
                    if getCurrentCamera == 'front':
                            planePos = bbox[5]
                    elif getCurrentCamera == 'back':
                        if (bbox[2] - cameraPos[2]) > 0:
                            planePos = bbox[2]
                    constructionPlanePos = [meshCOORD[0],meshCOORD[1],planePos*1.01]
                elif  getCurrentCamera == 'top' or getCurrentCamera == 'buttom':# check y asix
                    if getCurrentCamera == 'top':
                        planePos = bbox[4]
                    elif getCurrentCamera == 'buttom':
                        planePos = bbox[1]
                    constructionPlanePos = [meshCOORD[0],planePos*1.01,meshCOORD[2]]
                elif  getCurrentCamera == 'left' or getCurrentCamera == 'right':# check x asix
                    if getCurrentCamera == 'right':
                        planePos = bbox[3]
                    elif getCurrentCamera == 'left':
                        planePos = bbox[0]
                    constructionPlanePos = [planePos*1.01,meshCOORD[1],meshCOORD[2]]
                mc.move(constructionPlanePos[0],constructionPlanePos[1],constructionPlanePos[2],'instCutGrp', absolute=True, ws=1)
                recordHitPoint = (constructionPlanePos[0],constructionPlanePos[1],constructionPlanePos[2])
                if getCurrentCamera == 'front':
                    mc.setAttr("instCutGrp.rotateX", 180)
                elif getCurrentCamera == 'back':
                    mc.setAttr("instCutGrp.rotateX", 0)
                elif  getCurrentCamera == 'top':
                    mc.setAttr("instCutGrp.rotateX", 90)
                elif getCurrentCamera == 'buttom':
                    mc.setAttr("instCutGrp.rotateX", -90)
                elif  getCurrentCamera == 'left':
                    mc.setAttr("instCutGrp.rotateY", 90)
                elif getCurrentCamera == 'right':
                    mc.setAttr("instCutGrp.rotateY", -90)
                cameraUsed = getCurrentCamera
            if mc.objExists('instCutPlane'):
                selectionList = om.MSelectionList()
                selectionList.add('instCutPlane')
                dagPath = om.MDagPath()
                selectionList.getDagPath(0, dagPath)
                fnMeshA = om.MFnMesh(dagPath)
                global ctxPlane
                ctxPlane = 'drawPlane'
                if mc.draggerContext(ctxPlane, exists=True):
                    mc.deleteUI(ctxPlane)
                mc.draggerContext(ctxPlane, pressCommand = planeClick, dragCommand = planeDrag, name=ctxPlane, cursor='crossHair',undoMode='step')
                mc.setToolTo(ctxPlane)
                mc.scriptJob(runOnce=True, event=["ToolChanged", cut3DDraw])
   
def cutPlaneSnapRot():
    state = mc.radioButtonGrp('cutPlane', q=1 , sl=1)
    if state == 2:
        mc.setAttr(( "instCutPlane.rotateY" ),0)
    elif state == 3:
        mc.setAttr(( "instCutPlane.rotateZ" ),0)
    checkLongName = 'instCutGrp'
    parentNode = 'instCutGrp'
    cleanList = ('sampleCurv*','sampleMes*','rotationPlan*')
    for c in cleanList:
        if mc.objExists(c):
            mc.delete(c)
    gface, gHitp,cEdge,cEdgePos = getClosestEdge()
    checkCVList=mc.ls( mc.polyListComponentConversion (cEdge,fe=True,tv=True),flatten=True)
    mx,my,mz = mc.pointPosition(checkCVList[0],w=1)
    mc.polyPlane(w=1, h=1, sx=1, sy=1, ax=(0,1,0), cuv=2, ch=0, n='rotationPlane')
    mc.polyCreateFacet( p=[(mx, my, mz),(cEdgePos[0], cEdgePos[1], cEdgePos[2]),(gHitp[0], gHitp[1], gHitp[2])] )
    mc.rename('sampleMesh')
    mc.select("rotationPlane.vtx[0:2]", "sampleMesh.vtx[0:2]")
    CMD = 'snap3PointsTo3Points(0);'
    mel.eval(CMD)
    mc.parent('instCutGrp','rotationPlane')
    axes = ["X", "Y", "Z"]
    for a in axes:
        
        val = mc.getAttr( "instCutGrp.rotate" + a)
        valTmp = ''
        if val > 0:
            valTmp = val + 45
        else:
            valTmp = val - 45
        valNew = int (valTmp/90)
        mc.setAttr(( "instCutGrp.rotate" + a), (valNew*90))
    mc.parent('instCutGrp',w=1)
    mc.select(cl=1)
    for c in cleanList:
        if mc.objExists(c):
            mc.delete(c)

def getClosestEdge():
    gFace = ''
    gHitP = ''
    gFace,gHitP = getClosestMeshHit()
    listF2E=mc.ls( mc.polyListComponentConversion (gFace,ff=True,te=True),flatten=True)
    cEdge = ''
    smallestDist = 1000000
    cEdgePos = []
    for l in listF2E:
        mc.select(l)
        mc.polyToCurve(form=2, degree=1, conformToSmoothMeshPreview=1)
        sampleCurve = mc.ls(sl=1)
        selectionList = om.MSelectionList()
        selectionList.add(sampleCurve[0])
        dagPath = om.MDagPath()
        selectionList.getDagPath(0, dagPath)
        omCurveOut = om.MFnNurbsCurve(dagPath)
        pointInSpace = om.MPoint(gHitP[0],gHitP[1],gHitP[2])
        closestPoint = om.MPoint()
        closestPoint = omCurveOut.closestPoint(pointInSpace)
        getDist = math.sqrt( ((closestPoint[0] - gHitP[0])**2)  + ((closestPoint[1]- gHitP[1])**2) + ((closestPoint[2] - gHitP[2])**2))
        if getDist < smallestDist:
            smallestDist = getDist
            cEdge = l
            cEdgePos = [closestPoint[0],closestPoint[1],closestPoint[2]]
        mc.delete(sampleCurve)
    mc.select(cEdge)
    return(gFace,gHitP,cEdge,cEdgePos)

def getClosestMeshHit():
    global recordHitPoint
    shortDistanceCheck = 10000
    resultFace = []
    resultCV =[]
    resultHitPoint = []
    getFaceDist,getFace,getHitPoint  = getClosestPointOnFace(recordHitPoint)
    if getFaceDist < shortDistanceCheck:
        shortDistanceCheck = getFaceDist
        resultFace = getFace
        resultHitPoint = getHitPoint
    return (resultFace,resultHitPoint)

def getClosestPointOnFace(pos=[0,0,0]):
    global targetMmesh
    mVector = om2.MVector(pos)#using MVector type to represent position
    selectionList = om2.MSelectionList()
    selectionList.add(targetMmesh)
    dPath= selectionList.getDagPath(0)
    mMesh=om2.MFnMesh(dPath)
    ID = mMesh.getClosestPoint(om2.MPoint(mVector),space=om2.MSpace.kWorld)[1] #getting closest face ID
    closestPoint= mMesh.getClosestPoint(om2.MPoint(mVector),space=om2.MSpace.kWorld)[0]
    cpx = closestPoint[0]
    cpy = closestPoint[1]
    cpz = closestPoint[2]
    hitPointPosition = [cpx,cpy,cpz]
    hitFaceName = (targetMmesh +'.f['+str(ID)+']')
    getFaceDist = math.sqrt( ((pos[0] - cpx)**2)  + ((pos[1]- cpy)**2) + ((pos[2] - cpz)**2))
    return (getFaceDist, hitFaceName,hitPointPosition)

def get_face_normal(mesh, face_index):
    selection = om.MSelectionList()
    selection.add(mesh)
    dagPath = om.MDagPath()
    selection.getDagPath(0, dagPath)
    fnMesh = om.MFnMesh(dagPath)
    normal = om.MVector()
    fnMesh.getPolygonNormal(face_index, normal, om.MSpace.kWorld)
    return normal

def facePointOrder():
    selectionListX = om.MSelectionList()
    selectionListX.add('tempExtrudeBlock')
    dagPathX = om.MDagPath()
    selectionListX.getDagPath(0, dagPathX)
    faceIter = om.MItMeshPolygon(dagPathX)
    faceIndex = 0 
    vertexListX = om.MIntArray()
    faceIter.getVertices(vertexListX)
    vtxList = [vertexListX[i] for i in range(vertexListX.length())]
    zero_index = vtxList.index(0)
    vtxList = vtxList[zero_index:] + vtxList[:zero_index]
    return vtxList

def smoothALLCorner():
    VertexInitSelection = mc.ls(sl=1,fl=1)
    EdgeSel = mc.ls(mc.polyListComponentConversion(VertexInitSelection, te=1),fl=1)
    mc.select(EdgeSel)
    mc.polyExtrudeEdge( EdgeSel, kft=True, pvx= 0, pvy= 0, pvz= 0, divisions= 1, twist= 0, taper= 1, offset= 0, thickness= 0)
    newEdge = mc.ls(sl=1,fl=1)
    converted = mc.polyListComponentConversion(mc.polyListComponentConversion(newEdge, tf=1), fv=True, ff=True, fuv=True, fvf=True, te=True, internal=True)
    state = mc.radioButtonGrp('cutPlane',q=1, sl=1)
    mVTolerance = 1
    if state != 1:
        mVTolerance = 0.001
    createdNode = mc.polyBevel3(
        converted,
        fraction=0.5,
        offsetAsFraction=True,
        autoFit=True,
        depth=1,
        mitering=0,
        miterAlong=0,
        chamfer=True,
        segments=1,
        worldSpace=True,
        smoothingAngle=30,
        subdivideNgons=True,
        mergeVertices=True,
        mergeVertexTolerance=mVTolerance,
        miteringAngle=180,
        angleTolerance=180,
        constructionHistory=True,
        name = 'cutBevel'
    )
    mc.rename(createdNode,'cutBevel')
    mc.select('tempExtrudeBlock')
    mc.headsUpDisplay( 'HUDBevelStep', section=2, block=0, blockSize='large', label='Segments', labelFontSize='large', command=currentSegments, atr=1)

def currentSegments():
    if mc.objExists('cutBevel'):
        current = mc.getAttr('cutBevel.segments')
        return current
        
def smoothCutCorner():
    gP = facePointOrder()[-1]
    vertex_count = mc.polyEvaluate('tempExtrudeBlock', vertex=True)
    VertexInitSelection = 'tempExtrudeBlock.vtx['+ str(gP) +']'
    EdgeSel = mc.ls(mc.polyListComponentConversion(VertexInitSelection, te=1),fl=1)
    mc.select(EdgeSel)
    mc.polyExtrudeEdge( EdgeSel, kft=True, pvx= 0, pvy= 0, pvz= 0, divisions= 1, twist= 0, taper= 1, offset= 0, thickness= 0)
    newEdge = mc.ls(sl=1,fl=1)
    converted = mc.polyListComponentConversion(mc.polyListComponentConversion(newEdge, tf=1), fv=True, ff=True, fuv=True, fvf=True, te=True, internal=True)
    state = mc.radioButtonGrp('cutPlane',q=1, sl=1)
    mVTolerance = 1
    if state != 1:
        mVTolerance = 0.001
    createdNode = mc.polyBevel3(
        converted[0],
        fraction=0.5,
        offsetAsFraction=True,
        autoFit=True,
        depth=1,
        mitering=0,
        miterAlong=0,
        chamfer=True,
        segments=1,
        worldSpace=True,
        smoothingAngle=30,
        subdivideNgons=True,
        mergeVertices=True,
        mergeVertexTolerance=mVTolerance,
        miteringAngle=180,
        angleTolerance=180,
        constructionHistory=True,
        name = 'cutBevel'
    )
    mc.rename(createdNode,'cutBevel')
    mc.select('tempExtrudeBlock')
    mc.headsUpDisplay( 'HUDBevelStep', section=2, block=0, blockSize='large', label='Segments', labelFontSize='large', command=currentSegments, atr=1)

def cut3DDraw():
    global targetMmesh
    global storeCutCircleR
    storeCutCircleR = 0.01
    global storeCutCircleS
    storeCutCircleS = 16
    global tempExtrudeCurveP 
    global storeLongSide
    global cutType
    tempExtrudeCurveP = 0
    bbox = mc.exactWorldBoundingBox(targetMmesh)
    width = bbox[3] - bbox[0]
    height = bbox[4] - bbox[1]
    depth = bbox[5] - bbox[2]
    longest_edge = max(width, height, depth)
    storeLongSide = longest_edge
    cutPlane = mc.radioButtonGrp('cutPlane', q=1, sl=1)
    if cutType == 1:
        points = [(0, 0, 0), (0, 0, 0), (0, 0, 0)]
        mesh = mc.polyCreateFacet(p=points, n='tempExtrudeBlock')    
    elif cutType == 2:
        mc.polyPlane(w=0.1, h=0.1, sx=1, sy=1, axis=(0, 1, 0), ch=0,n='tempExtrudeBlock')
        mc.cluster('tempExtrudeBlock.vtx[2]',n='cutBoxMoveBase')
        mc.cluster('tempExtrudeBlock.vtx[3]',n='cutBoxMoveX')
        mc.cluster('tempExtrudeBlock.vtx[1]',n='cutBoxMove')
        mc.cluster('tempExtrudeBlock.vtx[0]',n='cutBoxMoveZ')
        mc.pointConstraint('cutBoxMoveHandle', 'cutBoxMoveXHandle', mo=True ,skip=['y','z'], w =1)
        mc.pointConstraint('cutBoxMoveHandle', 'cutBoxMoveZHandle', mo=True ,skip=['x','y'], w =1)
        mc.group('cutBoxMov*',n='cutBoxMoveGrp')
        mc.xform('cutBoxMoveGrp', ws=True, piv=[-0.05,0,-0.05])
        mc.parent('cutBoxMoveGrp', 'instCutGrp')
        mc.setAttr("cutBoxMoveGrp.rotate",0,0,0)
        getZ = mc.getAttr('instCutPlane.translateZ')
        mc.setAttr("cutBoxMoveGrp.translateZ", getZ)
        mc.group(empty=1,n='cutBoxMoveA')
        mc.group(empty=1,n='cutBoxMoveB')
        posA = mc.pointPosition('tempExtrudeBlock.vtx[2]', w = True)
        posB = mc.pointPosition('tempExtrudeBlock.vtx[1]', w = True)
        mc.setAttr('cutBoxMoveA.translate',posA[0],posA[1],posA[2])
        mc.setAttr('cutBoxMoveB.translate',posB[0],posB[1],posB[2])
        mc.pointConstraint('cutBoxMoveA', 'cutBoxMoveGrp', mo=True , w =1)
        mc.pointConstraint('cutBoxMoveB', 'cutBoxMoveHandle', mo=True , w =1,skip=['y'])
        mc.parent('cutBoxMoveB' ,'cutBoxMoveA')
        mc.setAttr("cutBoxMoveGrp.visibility",0)
        mc.setAttr("tempExtrudeBlock.visibility",0)
        mc.setAttr("cutBoxMoveA.hiddenInOutliner",1)
        #getRotY = mc.getAttr('instCutPlane.rotateY')
        #mc.setAttr('cutBoxMoveGrp.rotateY',getRotY)
    elif cutType == 3:
        if cutPlane == 2:
            hisNode = mc.polyCylinder(sc=0, r=1 ,h=0.001, sx= storeCutCircleS, sy=1, sz=0, axis=(0, 1, 0),rcp=0,createUVs=3,ch=1,n='tempExtrudeBlock')
            mc.setAttr('tempExtrudeBlock.scaleX',0.1*longest_edge)
            mc.setAttr('tempExtrudeBlock.scaleY',0.01)
            mc.setAttr('tempExtrudeBlock.scaleZ',0.1*longest_edge)
            mc.rename(hisNode[-1], 'cutCircleContral')
        elif cutPlane == 3:
            hisNode = mc.polyCylinder(sc=0, r=1 ,h=0.001, sx= storeCutCircleS, sy=1, sz=0, axis=(0, 0, 1),rcp=0,createUVs=3,ch=1,n='tempExtrudeBlock')
            mc.setAttr('tempExtrudeBlock.scaleX',0.1*longest_edge)
            mc.setAttr('tempExtrudeBlock.scaleY',0.1*longest_edge)
            mc.setAttr('tempExtrudeBlock.scaleZ',0.01)
            mc.rename(hisNode[-1], 'cutCircleContral')
        mc.setAttr('tempExtrudeBlock.visibility', 0)
        storeCutCircleR = 0.1*longest_edge
    if mc.objExists("cutBlockShader") == 0:
        shader=mc.shadingNode("surfaceShader", name = 'cutBlockShader',asShader=True)
        shading_group= mc.sets(name='cutBlockShaderSG',renderable=True,noSurfaceShader=True,empty=True)
        mc.connectAttr('cutBlockShader.outColor', 'cutBlockShaderSG.surfaceShader',f=1 )
        mc.setAttr("cutBlockShader.outColor", 0.65, 0, 0.85, type="double3")
        mc.setAttr("cutBlockShader.outTransparency", 0.85, 0.85, 0.85, type="double3")
    if mc.objExists("cutGirdLine"):
        mc.setAttr("cutGirdLine.lineColor", 0.25, 1, 1, type="double3")
    if mc.objExists("tempExtrudeBlock"):
        mc.select('tempExtrudeBlock')
        mc.setAttr('tempExtrudeBlock.hiddenInOutliner',1)
        mc.setAttr("tempExtrudeBlockShape.receiveShadows",0)
        mc.setAttr("tempExtrudeBlockShape.castsShadows",0)

    mc.setAttr("cutBlockShader.outColor", 0.65, 0, 0.85, type="double3")
    mc.hyperShade(assign="cutBlockShader") 
    if mc.objExists("instCutPlane"):
        selectionList = om.MSelectionList()
        selectionList.add('instCutPlane')
        dagPath = om.MDagPath()
        selectionList.getDagPath(0, dagPath)
        fnMeshA = om.MFnMesh(dagPath)
        if cutType == 1:
            global ctx
            ctx = 'drawBlock'
            if mc.draggerContext(ctx, exists=True):
                mc.deleteUI(ctx)
            mc.draggerContext(ctx, pressCommand = cutClick, rc = cutClean, dragCommand = cutDrag, name=ctx, cursor='crossHair',undoMode='step')
            mc.setToolTo(ctx)
            cutToolID = mc.scriptJob(runOnce=True, event=["ToolChanged", cut3DExtrude])
        elif cutType == 2:
            mc.select('tempExtrudeBlock')
            global ctxBox
            ctxBox = 'drawBox'
            if mc.draggerContext(ctxBox, exists=True):
                mc.deleteUI(ctxBox)
            mc.draggerContext(ctxBox, pressCommand = cutBoxClick, dragCommand = cutBoxDrag, name=ctxBox, fnz=cutEnd, cursor='crossHair',undoMode='step')
            mc.setToolTo(ctxBox)
            cutToolID = mc.scriptJob(runOnce=True, event=["ToolChanged", cut3DExtrude])
        elif cutType == 3:
            mc.select('tempExtrudeBlock')
            global ctxCircle
            ctxCircle = 'drawCircle'
            if mc.draggerContext(ctxCircle, exists=True):
                mc.deleteUI(ctxCircle)
            mc.draggerContext(ctxCircle, pressCommand = cutCircleClick, dragCommand = cutCircleDrag, name=ctxCircle,fnz=cutEnd, cursor='crossHair',undoMode='step')
            mc.setToolTo(ctxCircle)
            cutToolID = mc.scriptJob(runOnce=True, event=["ToolChanged", cut3DExtrude])
 
 
def extrudeClick():
    checCurrentkHUD =  mc.headsUpDisplay(lh=1)
    if checCurrentkHUD is not None:
        for t in checCurrentkHUD:
            if 'HUDBevelStep' in t:
                mc.headsUpDisplay(t, rem=1)
    global curExtrudeCount
    global ctxExtrude
    global screenX,screenY
    vpX, vpY, _ = mc.draggerContext(ctxExtrude, query=True, anchorPoint=True)
    if mc.objExists('cutExtrudeNode'):
        if screenX > vpX:
            curExtrudeCount = curExtrudeCount - (0.01*targetMmeshScale)
        else:
            curExtrudeCount = curExtrudeCount + (0.01*targetMmeshScale)
        screenX = vpX
        if curExtrudeCount < 0.01:
            curExtrudeCount = 0.01
        mc.setAttr('cutExtrudeNode.thickness',(curExtrudeCount))
        mc.refresh(cv=True,f=True)

def extrudeDrag():
    global ctxExtrude
    global curExtrudeCount
    global screenX,screenY
    global targetMmeshScale
    modifiers = mc.getModifiers()
    vpX, vpY, _ = mc.draggerContext(ctxExtrude, query=True, dragPoint=True)
    if mc.objExists('cutExtrudeNode'):
        if(modifiers == 4): 
            if screenX > vpX:
                curExtrudeCount = curExtrudeCount - (0.001*targetMmeshScale)
            else:
                curExtrudeCount = curExtrudeCount + (0.001*targetMmeshScale)
        else:
            if screenX > vpX:
                curExtrudeCount = curExtrudeCount - (0.05*targetMmeshScale)
            else:
                curExtrudeCount = curExtrudeCount + (0.05*targetMmeshScale)
        screenX = vpX
        if curExtrudeCount < 0.01:
            curExtrudeCount = 0.01
        mc.setAttr('cutExtrudeNode.thickness',(curExtrudeCount))
        mc.refresh(cv=True,f=True)


def planeDrag():
    modifiers = mc.getModifiers()
    state = mc.radioButtonGrp('cutPlane',q=1, sl=1)
    global cutPlaneRotCount
    global cutPlaneSizeCount
    global ctxPlane
    global screenX,screenY
    global fnMeshA
    global targetMmesh
    global recordHitPoint
    global recordHitFaceName
    global recordAlignAngle
    selectionTarget = om.MSelectionList()
    selectionTarget.add(targetMmesh)
    dagPathTarget = om.MDagPath()
    selectionTarget.getDagPath(0, dagPathTarget)
    fnMeshTarget = om.MFnMesh(dagPathTarget)
    vpX, vpY, _ = mc.draggerContext(ctxPlane, query=True, dragPoint=True)
    if modifiers == 1:
        if screenX > vpX:
            cutPlaneRotCount = cutPlaneRotCount -1
        else:
            cutPlaneRotCount = cutPlaneRotCount + 1
        if cutPlaneRotCount > 45:
            cutPlaneRotCount = 45
        elif cutPlaneRotCount < -45:
            cutPlaneRotCount = -45  
        if state == 2:
            mc.setAttr("instCutPlane.rotateY",cutPlaneRotCount)
        elif state == 3:
            mc.setAttr("instCutPlane.rotateZ",cutPlaneRotCount)
        screenX = vpX
        mc.refresh(cv=True,f=True)
    elif modifiers == 4:
        if screenX > vpX:
            cutPlaneSizeCount = cutPlaneSizeCount -1
        else:
            cutPlaneSizeCount = cutPlaneSizeCount + 1

        mc.setAttr("instCutPlane.curGridSizeLink",cutPlaneSizeCount)
        screenX = vpX
        mc.refresh(cv=True,f=True)
    else:  
        screenX = vpX
        screenY = vpY
        pos = om.MPoint()
        dir = om.MVector()
        omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
        pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
        hitpoint = om.MFloatPoint()
        hitFace = om.MScriptUtil()
        hitFace.createFromInt(0)
        hitFacePtr = hitFace.asIntPtr()
        intersection = fnMeshTarget.closestIntersection(
        om.MFloatPoint(pos2),
        om.MFloatVector(dir),
        None,
        None,
        False,
        om.MSpace.kWorld,
        100000,
        False,
        None,
        hitpoint,
        None,
        hitFacePtr,
        None,
        None,
        None)
        if intersection:
            hitFace = om.MScriptUtil(hitFacePtr).asInt()
            hitFaceName = (targetMmesh + '.f[' + str(hitFace) +']')
            obj_matrix = om.MMatrix()
            matrix_list = mc.xform(targetMmesh, query=True, worldSpace=True, matrix=True)
            om.MScriptUtil.createMatrixFromList(matrix_list, obj_matrix)
            face_normals_text = mc.polyInfo(hitFaceName, faceNormals=True)[0]
            face_normals = [float(digit) for digit in re.findall(r'-?\d*\.\d*', face_normals_text)]
            v = om.MVector(face_normals[0], face_normals[1], face_normals[2]) * obj_matrix
            upvector = om.MVector(0, 1, 0)
            getHitNormal = v
            quat = om.MQuaternion(upvector, getHitNormal)
            quatAsEuler = quat.asEulerRotation()
            rx, ry, rz = math.degrees(quatAsEuler.x), math.degrees(quatAsEuler.y), math.degrees(quatAsEuler.z)
            recordHitPoint = [hitpoint.x, hitpoint.y, hitpoint.z]
            if state == 2:
                mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'instCutGrp' , absolute=True, ws=1)
            elif state == 3:
                getCurrentOrPlaneX = mc.getAttr('instCutGrp.translateX')
                getCurrentOrPlaneY = mc.getAttr('instCutGrp.translateY')
                getCurrentOrPlaneZ = mc.getAttr('instCutGrp.translateZ')
                if cameraUsed == 'front' or cameraUsed == 'back':
                    mc.move(hitpoint.x, hitpoint.y, getCurrentOrPlaneZ, 'instCutGrp' , absolute=True, ws=1)
    
                elif  cameraUsed == 'top' or cameraUsed == 'buttom':
                    mc.move(hitpoint.x, getCurrentOrPlaneY, hitpoint.z, 'instCutGrp' , absolute=True, ws=1)
    
                elif  cameraUsed == 'left' or cameraUsed == 'right':
                    mc.move(getCurrentOrPlaneX, hitpoint.y, hitpoint.z, 'instCutGrp' , absolute=True, ws=1)
                
            if hitFaceName == recordHitFaceName:
                pass
            else:
                if state == 2:
                    mc.setAttr('instCutGrp.rotate', rx, ry, rz)
                recordAlignAngle = 0
                recordHitFaceName = hitFaceName
            mc.refresh(cv=True,f=True)
        
def planeClick():
    global recordHitPoint
    global recordHitFaceName
    global recordAlignAngle
    global cameraUsed
    modifiers = mc.getModifiers()
    if modifiers == 5:
        cutPlaneSnapRot()
        mc.refresh(cv=True,f=True)
        recordAlignAngle = 1
    mc.setAttr( 'instCutPlane.visibility',1)
    state = mc.radioButtonGrp('cutPlane',q=1, sl=1)
    global ctxPlane
    global screenX,screenY
    global fnMeshA
    global targetMmesh
    global cutPlaneRotCount
    global cutPlaneSizeCount
    cutPlaneRotCount = mc.intSliderGrp("cutGridRot", q=1, v=1)
    cutPlaneSizeCount = mc.intSliderGrp("cutGridSize", q=1, v=1)
    selectionTarget = om.MSelectionList()
    selectionTarget.add(targetMmesh)
    dagPathTarget = om.MDagPath()
    selectionTarget.getDagPath(0, dagPathTarget)
    fnMeshTarget = om.MFnMesh(dagPathTarget)
    vpX, vpY, _ = mc.draggerContext(ctxPlane, query=True, anchorPoint=True)
    screenX = vpX
    screenY = vpY
    pos = om.MPoint()
    dir = om.MVector()
    omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
    pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
    hitpoint = om.MFloatPoint()
    hitFace = om.MScriptUtil()
    hitFace.createFromInt(0)
    hitFacePtr = hitFace.asIntPtr()
    intersection = fnMeshTarget.closestIntersection(
    om.MFloatPoint(pos2),
    om.MFloatVector(dir),
    None,
    None,
    False,
    om.MSpace.kWorld,
    100000,
    False,
    None,
    hitpoint,
    None,
    hitFacePtr,
    None,
    None,
    None)
    if intersection:
        hitFace = om.MScriptUtil(hitFacePtr).asInt()
        hitFaceName = (targetMmesh + '.f[' + str(hitFace) +']')
        recordHitFaceName = hitFaceName
        obj_matrix = om.MMatrix()
        matrix_list = mc.xform(targetMmesh, query=True, worldSpace=True, matrix=True)
        om.MScriptUtil.createMatrixFromList(matrix_list, obj_matrix)
        face_normals_text = mc.polyInfo(hitFaceName, faceNormals=True)[0]
        face_normals = [float(digit) for digit in re.findall(r'-?\d*\.\d*', face_normals_text)]
        v = om.MVector(face_normals[0], face_normals[1], face_normals[2]) * obj_matrix
        upvector = om.MVector(0, 1, 0)
        getHitNormal = v
        quat = om.MQuaternion(upvector, getHitNormal)
        quatAsEuler = quat.asEulerRotation()
        rx, ry, rz = math.degrees(quatAsEuler.x), math.degrees(quatAsEuler.y), math.degrees(quatAsEuler.z)
        if state == 2:
            mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'instCutGrp' , absolute=True, ws=1)
        elif state == 3:
            getCurrentOrPlaneX = mc.getAttr('instCutGrp.translateX')
            getCurrentOrPlaneY = mc.getAttr('instCutGrp.translateY')
            getCurrentOrPlaneZ = mc.getAttr('instCutGrp.translateZ')
            if cameraUsed == 'front' or cameraUsed == 'back':
                mc.move(hitpoint.x, hitpoint.y, getCurrentOrPlaneZ, 'instCutGrp' , absolute=True, ws=1)
            elif  cameraUsed == 'top' or cameraUsed == 'buttom':
                mc.move(hitpoint.x, getCurrentOrPlaneY, hitpoint.z, 'instCutGrp' , absolute=True, ws=1)
            elif  cameraUsed == 'left' or cameraUsed == 'right':
                mc.move(getCurrentOrPlaneX, hitpoint.y, hitpoint.z, 'instCutGrp' , absolute=True, ws=1)
        if modifiers == 0:
            if state == 2:
                if recordAlignAngle == 0:
                    mc.setAttr('instCutGrp.rotate', rx, ry, rz)

def cutGridReset():
    saveCurrentSel = mc.ls(sl=1,fl=1)
    script_jobs = mc.scriptJob(listJobs=True)
    cleanIDList = ('extrudeEndCut','cut2DGoLock','cutFiz','cut3DDraw')
    for c in cleanIDList:
        for job in script_jobs:
            if c in job:
                job_id = int(job.split(":")[0])
                mc.evalDeferred(lambda: mc.scriptJob(kill=job_id, force=True))
                #mc.scriptJob(kill=job_id, force=True)
                print('killed')
    checCurrentkHUD =  mc.headsUpDisplay(lh=1)
    if checCurrentkHUD is not None:
        for t in checCurrentkHUD:
            if 'HUDBevelStep' in t:
                mc.headsUpDisplay(t, rem=1)
    global oldShader
    global targetMmesh
    cleanList = ('targetMeshLayer','extudeCluster','tempExtrudeCurve','tempExtrudeBlock','instCut*','cutBlockShader','blockFizMesh','cutGird*','sampleCurv*','sampleMes*','rotationPlan*','cutBoxMove*','tempLoft*')
    for c in cleanList:
        if mc.objExists(c):
            mc.delete(c)
    mc.radioButtonGrp('cutPlane', e=1,en=1)
    currentSel = mc.ls(sl=1)
    if currentSel:
        state = 0
        if mc.nodeType(currentSel) == 'transform': 
            shapes = mc.listRelatives(currentSel, shapes=True) or []
            if any(mc.nodeType(shape) == 'mesh' for shape in shapes):
                try:
                    mc.hyperShade(assign= oldShader) 
                except:
                    pass
    cameras = mc.ls(type='camera')
    camera_transforms = mc.listRelatives(cameras, parent=True)
    for c in camera_transforms:
        lockAttr = ('tx','ty','tz','rx','ry','rz','sx','sy','sz')
        for k in lockAttr:
            mc.setAttr((c + '.'  + k), lock=0)
    global recordHitPoint
    recordHitPoint = [0,0,0]
    global cameraUsed
    cameraUsed = []
    mc.setToolTo('selectSuperContext')
    mc.iconTextButton('cutGoDrawButton',e=1, en=1)
    mc.iconTextButton('cutGoBoxButton',e=1, en=1)
    mc.iconTextButton('cutGoCircleButton',e=1, en=1)
    if saveCurrentSel:
        mc.select(saveCurrentSel)
        
def cutEnd():
    global cameraTrans
    lockAttr = ('tx','ty','tz','rx','ry','rz','sx','sy','sz')
    for k in lockAttr:
        mc.setAttr((cameraTrans[0] + '.'  + k), lock=0)

def cutFiz():
    global targetMmesh
    checCurrentkHUD =  mc.headsUpDisplay(lh=1)
    if checCurrentkHUD is not None:
        for t in checCurrentkHUD:
            if 'HUDBevelStep' in t:
                mc.headsUpDisplay(t, rem=1)
    if mc.objExists('tempExtrudeBlock'):
        mc.delete('tempExtrudeBlock',ch=1)
        view = omui.M3dView.active3dView()
        cam = om.MDagPath()
        view.getCamera(cam)
        camPath = cam.fullPathName()
        cameraTrans = mc.listRelatives(camPath,type='transform',p=True)
        camPivot = mc.xform(cameraTrans , q=1, ws=1, rp=1)
        is_ortho = mc.camera(cameraTrans, query=True, orthographic=True)
        face_count = mc.polyEvaluate('tempExtrudeBlock', face=True)
        if face_count > 1:
            getLarge = getLargeAreaFace()
            allFace = mc.ls('tempExtrudeBlock.f[*]',fl=1)
            allFace.remove(getLarge)
            mc.delete(allFace)
        mc.polyExtrudeFacet(constructionHistory = 1, keepFacesTogether= 1, ltz = 0.001)
        newFace = mc.ls(sl=1,fl=1)
        mc.select('tempExtrudeBlock.f[0]')
        mc.GrowPolygonSelectionRegion()
        mc.select('tempExtrudeBlock.f[0]',d=1)
        mc.delete()
        try:
            mc.polySeparate('tempExtrudeBlock',ch=0)
        except:
            pass
        testMesh = mc.ls(sl=1,fl=1)
        mc.CenterPivot()
        worldFaceA = mc.xform(testMesh[0], q=1, ws=1, piv=1)
        worldFaceB = mc.xform(testMesh[1], q=1, ws=1, piv=1)
        distA = math.sqrt( ((worldFaceA[0] - camPivot[0])**2)  + ((worldFaceA[1] - camPivot[1])**2)  + ((worldFaceA[2] - camPivot[2])**2) )
        distB = math.sqrt( ((worldFaceB[0] - camPivot[0])**2)  + ((worldFaceB[1] - camPivot[1])**2)  + ((worldFaceB[2] - camPivot[2])**2) )
        blockFizMesh = ''
        if distA > distB:
            mc.delete(testMesh[1])
            blockFizMesh = testMesh[0]
        else:
            mc.delete(testMesh[0])
            blockFizMesh = testMesh[1]
        mc.select(blockFizMesh +'.f[0]')
        if is_ortho == 1:# bug
            bbox = mc.exactWorldBoundingBox(targetMmesh)
            width = bbox[3] - bbox[0]
            height = bbox[4] - bbox[1]
            depth = bbox[5] - bbox[2]
            longest_edge = max(width, height, depth)
            mc.polyExtrudeFacet(constructionHistory = 1, keepFacesTogether= 1, thickness = longest_edge*1.05)
            mc.makeIdentity('tempExtrudeBlock', apply=True, t=1, r=1, s=1, n=2)
            value_before = mc.getAttr(blockFizMesh + '.center')[0]
            mc.setAttr(blockFizMesh + '.translateX', -value_before[0])
            mc.setAttr(blockFizMesh + '.translateY', -value_before[1])
            mc.setAttr(blockFizMesh + '.translateZ', -value_before[2])
            mc.makeIdentity(blockFizMesh, apply=True, t=1, r=1, s=1, n=2)
            if 'front' in cameraTrans[0]  or 'back' in cameraTrans[0]:
                mc.setAttr(blockFizMesh + '.translateX', value_before[0])
                mc.setAttr(blockFizMesh + '.translateY', value_before[1])
                mc.setAttr(blockFizMesh + '.translateZ', 0)
            elif 'top' in cameraTrans[0]  or 'buttom' in cameraTrans[0]:
                mc.setAttr(blockFizMesh + '.translateX', value_before[0])
                mc.setAttr(blockFizMesh + '.translateY', 0)
                mc.setAttr(blockFizMesh + '.translateZ', value_before[2])
            elif  'left' in cameraTrans[0] or 'right' in cameraTrans[0] or 'side' in cameraTrans[0]:
                mc.setAttr(blockFizMesh + '.translateX', 0)
                mc.setAttr(blockFizMesh + '.translateY', value_before[1])
                mc.setAttr(blockFizMesh + '.translateZ', value_before[2])
        else:
            getFaceDist,getFace,getHitPoint  = getClosestPointOnFace(camPivot)
            nearDist = math.sqrt( ((getHitPoint[0] - camPivot[0])**2)  + ((getHitPoint[1] - camPivot[1])**2)  + ((getHitPoint[2] - camPivot[2])**2) )
            distA = 0.105
            distScaleNear = nearDist / distA / 1.05
            checkFar = getFurthestPoint(camPivot)
            farDist = math.sqrt( ((checkFar[0] - camPivot[0])**2)  + ((checkFar[1] - camPivot[1])**2)  + ((checkFar[2] - camPivot[2])**2) )
            distScaleFar = farDist / distA 
            mc.polyExtrudeFacet(constructionHistory = 1, keepFacesTogether= 1, ltz = 0.001)
            mc.ConvertSelectionToVertices()
            farPoint = mc.ls(sl=1,fl=1)
            mc.CreateCluster()
            cName = mc.ls(sl=1,fl=1)
            mc.rename(cName[0],'extudeCluster')
            mc.xform('extudeCluster', ws=True, piv=(camPivot[0], camPivot[1], camPivot[2]))
            mc.select(blockFizMesh+ '.vtx[*]')
            mc.select(farPoint,d=1)
            mc.CreateCluster()
            cName = mc.ls(sl=1,fl=1)
            mc.rename(cName[0],'baseCluster')
            mc.xform('baseCluster', ws=True, piv=(camPivot[0], camPivot[1], camPivot[2]))
            mc.setAttr("extudeCluster.scale", distScaleFar,distScaleFar,distScaleFar)
            mc.setAttr("baseCluster.scale", distScaleNear,distScaleNear,distScaleNear)
        mc.delete(blockFizMesh,ch=1)
        mc.select(blockFizMesh)
        mc.CenterPivot()
        useOwnCutterShape()
    cleanList = ('extudeCluster','tempExtrudeBlock','cutBlockShader','blockFizMesh','cutBoxMove*')
    for c in cleanList:
        if mc.objExists(c):
            mc.delete(c)
    mc.setToolTo('moveSuperContext')
    mc.radioButtonGrp('cutPlane', e=1,en=1)
    mc.iconTextButton('cutGoDrawButton',e=1, en=1)
    mc.iconTextButton('cutGoBoxButton',e=1, en=1)
    mc.iconTextButton('cutGoCircleButton',e=1, en=1)
    currentCutter = mc.ls(sl=1,fl=1)
    if mc.objExists('instCutGrp'): 
        mc.parent(currentCutter[0],'instCutGrp')
        mc.makeIdentity(currentCutter[0], apply=True, translate=True, rotate=True, scale=True, normal=False, preserveNormals=True)
        mc.delete(ch=1)
        beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
        mc.parent(currentCutter[0], beseMesh + '_cutterGrp')
        mc.CenterPivot()
    checkAuto = mc.checkBox('autoOffP', q=1,v=1 )
    if checkAuto == 1:
        mc.evalDeferred('cutGridReset()')
        cutGridReset()
    mc.setToolTo('moveSuperContext')
       
def getFurthestPoint(pivot):
    global targetMmesh
    selection_list = om2.MSelectionList()
    selection_list.add(targetMmesh)
    dag_path = selection_list.getDagPath(0)
    mesh_fn = om2.MFnMesh(dag_path)
    vertices = mesh_fn.getPoints(om2.MSpace.kWorld)
    furthest_distance = 0
    furthest_point = None
    
    for vertex in vertices:
        distance = (om2.MVector(vertex.x, vertex.y, vertex.z) - om2.MVector(pivot)).length()
        
        if distance > furthest_distance:
            furthest_distance = distance
            furthest_point = vertex
    
    return furthest_point
    
def getLargeAreaFace():
    selectionList = om2.MSelectionList()
    selectionList.add('tempExtrudeBlock')
    dag, obj = selectionList.getComponent(0)
    it = om2.MItMeshPolygon(dag, obj)
    max_area = 0
    largest_face_index = -1
    while not it.isDone():
        area = it.getArea()
        if area > max_area:
            max_area = area
            largest_face_index = it.index()
        it.next()
    if largest_face_index != -1:
        return ('tempExtrudeBlock.f[' + str(largest_face_index) + ']')

def cutClick():
    checCurrentkHUD =  mc.headsUpDisplay(lh=1)
    if checCurrentkHUD is not None:
        for t in checCurrentkHUD:
            if 'HUDBevelStep' in t:
                mc.headsUpDisplay(t, rem=1)
    global curBevelCount
    global clickNo
    global ctx
    global screenX,screenY
    global fnMeshA
    curBevelCount = 0
    
    if mc.objExists('cutBevel'):
        mc.delete('tempExtrudeBlock',ch=1)
        face_count = mc.polyEvaluate('tempExtrudeBlock', face=True)
        if face_count > 1:
            getLarge = getLargeAreaFace()
            allFace = mc.ls('tempExtrudeBlock.f[*]',fl=1)
            allFace.remove(getLarge)
            mc.delete(allFace)
    modifiers = mc.getModifiers()
    if(modifiers == 1):
        if clickNo > 3:
            smoothCutCorner()
    elif(modifiers == 5):
        if clickNo > 3:
            smoothALLCorner()
    elif(modifiers == 13):
        mc.CenterPivot('tempExtrudeBlock')
        mc.select('tempExtrudeBlock')
        mc.BakeCustomPivot()
    else:
        vpX, vpY, _ = mc.draggerContext(ctx, query=True, anchorPoint=True)
        screenX = vpX
        screenY = vpY
        pos = om.MPoint()
        dir = om.MVector()
        omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
        pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
        hitpoint = om.MFloatPoint()
        hitFace = om.MScriptUtil()
        hitFace.createFromInt(0)
        hitFacePtr = hitFace.asIntPtr()
        intersection = fnMeshA.closestIntersection(
        om.MFloatPoint(pos2),
        om.MFloatVector(dir),
        None,
        None,
        False,
        om.MSpace.kWorld,
        100000,
        False,
        None,
        hitpoint,
        None,
        hitFacePtr,
        None,
        None,
        None)
        if intersection:
            if(modifiers == 4):
                hitFace = om.MScriptUtil(hitFacePtr).asInt()
                posNew = om2.MPoint(hitpoint.x, hitpoint.y, hitpoint.z) 
                sel = om2.MSelectionList()
                sel.add('instCutPlane')
                fnMeshB = om2.MFnMesh(sel.getDagPath(0))
                face_vertices = fnMeshB.getPolygonVertices(hitFace)  
                vertex_distances = ((vertex, fnMeshB.getPoint(vertex, om2.MSpace.kWorld).distanceTo(posNew))for vertex in face_vertices)
                lockGridID = min(vertex_distances, key=operator.itemgetter(1))[0]
                posiV = mc.pointPosition('instCutPlane.vtx[' +  str(lockGridID)  + ']', w = True)
                if clickNo == 0:
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[0]' , absolute=True, ws=1)
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[1]' , absolute=True, ws=1)
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo == 1:
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[1]' , absolute=True, ws=1)
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo == 2:
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo > 2:
                    xc = mc.ls((mc.polyListComponentConversion('tempExtrudeBlock.vtx[0]', te=1)),fl=1) 
                    vertex_count = int(xc[-1].split('[')[-1].split(']')[0])
                    mc.polySplit('tempExtrudeBlock',ch=0, s=1, sma=0, ip=(vertex_count,0.5))
                    gP = facePointOrder()[-1]
                    mc.move(posiV[0],posiV[1],posiV[2], ('tempExtrudeBlock.vtx['+ str(gP)+ ']') , absolute=True, ws=1)
                    mc.delete('tempExtrudeBlock', ch=1)
            else:
                if clickNo == 0:
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[0]' , absolute=True, ws=1)
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[1]' , absolute=True, ws=1)
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo == 1:
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[1]' , absolute=True, ws=1)
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo == 2:
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo > 2:
                    xc = mc.ls((mc.polyListComponentConversion('tempExtrudeBlock.vtx[0]', te=1)),fl=1) 
                    vertex_count = int(xc[-1].split('[')[-1].split(']')[0])
                    mc.polySplit('tempExtrudeBlock',ch=0, s=1, sma=0, ip=(vertex_count,0.5))
                    gP = facePointOrder()[-1]
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, ('tempExtrudeBlock.vtx['+ str(gP)+ ']') , absolute=True, ws=1)
                    mc.delete('tempExtrudeBlock', ch=1)
            mc.refresh(cv=True,f=True)

def cutDrag():
    modifiers = mc.getModifiers()
    global curBevelCount
    global clickNo
    global ctx
    global screenX,screenY
    global fnMeshA
    vpX, vpY, _ = mc.draggerContext(ctx, query=True, dragPoint=True)
    if mc.objExists('cutBevel'):
        if screenX > vpX:
            curBevelCount = curBevelCount -1
        else:
            curBevelCount = curBevelCount + 1
        screenX = vpX
        
        if(modifiers == 4):
            fra = curBevelCount * 0.01
            if fra < 0.01:
                fra = 0.01
            mc.setAttr('cutBevel.fraction',(fra))
        elif(modifiers == 5):
            seg = int(curBevelCount *0.2)
            if seg < 1:
                seg = 1
            mc.setAttr('cutBevel.segments',(seg))
        mc.refresh(cv=True,f=True)
    else:
        screenX = vpX
        screenY = vpY
        pos = om.MPoint()
        dir = om.MVector()
        omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
        pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
        hitpoint = om.MFloatPoint()
        hitFace = om.MScriptUtil()
        hitFace.createFromInt(0)
        hitFacePtr = hitFace.asIntPtr()
        intersection = fnMeshA.closestIntersection(
        om.MFloatPoint(pos2),
        om.MFloatVector(dir),
        None,
        None,
        False,
        om.MSpace.kWorld,
        100000,
        False,
        None,
        hitpoint,
        None,
        hitFacePtr,
        None,
        None,
        None)
        if intersection:
            if(modifiers == 4):
                hitFace = om.MScriptUtil(hitFacePtr).asInt()
                posNew = om2.MPoint(hitpoint.x, hitpoint.y, hitpoint.z) 
                sel = om2.MSelectionList()
                sel.add('instCutPlane')
                fnMeshB = om2.MFnMesh(sel.getDagPath(0))
                face_vertices = fnMeshB.getPolygonVertices(hitFace)  
                vertex_distances = ((vertex, fnMeshB.getPoint(vertex, om2.MSpace.kWorld).distanceTo(posNew))for vertex in face_vertices)
                lockGridID = min(vertex_distances, key=operator.itemgetter(1))[0]
                posiV = mc.pointPosition('instCutPlane.vtx[' +  str(lockGridID)  + ']', w = True)
                if clickNo == 0:
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[0]' , absolute=True, ws=1)
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[1]' , absolute=True, ws=1)
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo == 1:
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[1]' , absolute=True, ws=1)
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo == 2:
                    mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo > 2:
                    gP = facePointOrder()[-1]
                    mc.move(posiV[0],posiV[1],posiV[2], ('tempExtrudeBlock.vtx['+ str(gP)+ ']') , absolute=True, ws=1)
            elif(modifiers == 13):
                mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock' , absolute=True, ws=1)
            else:
                if clickNo == 0:
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[0]' , absolute=True, ws=1)
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[1]' , absolute=True, ws=1)
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo == 1:
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[1]' , absolute=True, ws=1)
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo == 2:
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock.vtx[2]' , absolute=True, ws=1)
                if clickNo > 2:
                    gP = facePointOrder()[-1]
                    mc.move(hitpoint.x, hitpoint.y, hitpoint.z, ('tempExtrudeBlock.vtx['+ str(gP)+ ']') , absolute=True, ws=1)
                    
            mc.refresh(cv=True,f=True)
    
def cutClean():
    global clickNo
    clickNo = clickNo +1
    if mc.objExists('tempExtrudeBlock'):
        mc.select('tempExtrudeBlock')

def currentCutCircleSD():
    if mc.objExists('cutCircleContral'):
        current = mc.getAttr('cutCircleContral.subdivisionsAxis')
        return current
           
def cutCircleClick():
    checCurrentkHUD =  mc.headsUpDisplay(lh=1)
    anyDisp = 0
    if checCurrentkHUD is not None:
        for t in checCurrentkHUD:
            if 'HUDBevelStep' in t:
                anyDisp = 1
    if anyDisp == 0:
        mc.headsUpDisplay( 'HUDBevelStep', section=2, block=0, blockSize='large', label='Segments', labelFontSize='large', command=currentCutCircleSD, atr=1)
    #cutPlane = mc.radioButtonGrp('cutPlane', q=1, sl=1)
    #if cutPlane == 1:
    #    getRotZ = mc.getAttr('instCutPlane.rotateZ')
    #    mc.setAttr('cutBoxMoveGrp.rotateZ',getRotZ)
    #elif cutPlane == 2:       
    #    getRotY = mc.getAttr('instCutPlane.rotateY')
    #    mc.setAttr('cutBoxMoveGrp.rotateY',getRotY)
    #else:
    #    getRotZ = mc.getAttr('instCutPlane.rotateZ')
    #    mc.setAttr('cutBoxMoveGrp.rotateZ',getRotZ)
                
    global ctxCircle
    global screenX,screenY
    global fnMeshA
    global storeCutCircleR
    global storeCutCircleS
    global storeLongSide
    modifiers = mc.getModifiers()
    vpX, vpY, _ = mc.draggerContext(ctxCircle, query=True, anchorPoint=True)
    screenX = vpX
    screenY = vpY
    pos = om.MPoint()
    dir = om.MVector()
    omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
    pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
    hitpoint = om.MFloatPoint()
    hitFace = om.MScriptUtil()
    hitFace.createFromInt(0)
    hitFacePtr = hitFace.asIntPtr()
    intersection = fnMeshA.closestIntersection(
    om.MFloatPoint(pos2),
    om.MFloatVector(dir),
    None,
    None,
    False,
    om.MSpace.kWorld,
    100000,
    False,
    None,
    hitpoint,
    None,
    hitFacePtr,
    None,
    None,
    None)
    if intersection:
        rrr = mc.getAttr('instCutGrp.rotate')
        mc.setAttr('tempExtrudeBlock.visibility',1)
        if(modifiers == 4):
            hitFace = om.MScriptUtil(hitFacePtr).asInt()
            posNew = om2.MPoint(hitpoint.x, hitpoint.y, hitpoint.z) 
            sel = om2.MSelectionList()
            sel.add('instCutPlane')
            fnMeshB = om2.MFnMesh(sel.getDagPath(0))
            face_vertices = fnMeshB.getPolygonVertices(hitFace)  
            vertex_distances = ((vertex, fnMeshB.getPoint(vertex, om2.MSpace.kWorld).distanceTo(posNew))for vertex in face_vertices)
            lockGridID = min(vertex_distances, key=operator.itemgetter(1))[0]
            posiV = mc.pointPosition('instCutPlane.vtx[' +  str(lockGridID)  + ']', w = True)
            mc.move(posiV[0],posiV[1],posiV[2], 'tempExtrudeBlock' , absolute=True, ws=1)
        else:
            mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock' , absolute=True, ws=1)
        mc.setAttr('tempExtrudeBlock.rotate', rrr[0][0], rrr[0][1], rrr[0][2])
        mc.refresh(cv=True,f=True)

def cutCircleDrag():
    modifiers = mc.getModifiers()
    state = mc.radioButtonGrp('cutPlane', q=1, sl=1)
    global ctxCircle
    global screenX,screenY
    global fnMeshA
    global storeCutCircleR
    global storeCutCircleS
    global storeLongSide
    global storeOrtho
    vpX, vpY, _ = mc.draggerContext(ctxCircle, query=True, dragPoint=True)
    if(modifiers == 0) or (modifiers == 4):
        if mc.objExists('cutCircleContral'):
            fra = 0
            if state == 1:
                if storeCutCircleR < 0.01:
                    if screenX > vpX:
                        storeCutCircleR = storeCutCircleR - 0.0001
                    else:
                        storeCutCircleR = storeCutCircleR + 0.0001
                else:
                    if screenX > vpX:
                        storeCutCircleR = storeCutCircleR - 0.0002
                    else:
                        storeCutCircleR = storeCutCircleR + 0.0002
            else:
                if storeCutCircleR < 0.01:
                    if screenX > vpX:
                        storeCutCircleR = storeCutCircleR - (0.001*storeLongSide)
                    else:
                        storeCutCircleR = storeCutCircleR + (0.001*storeLongSide)
                else:
                    if screenX > vpX:
                        storeCutCircleR = storeCutCircleR - (0.002*storeLongSide)
                    else:
                        storeCutCircleR = storeCutCircleR + (0.002*storeLongSide)
            fra = storeCutCircleR 
            if fra < 0.0001:
                fra = 0.0001
            if storeOrtho == 1:
                mc.setAttr('tempExtrudeBlock.scaleX',(fra)*storeLongSide*5)
                mc.setAttr('tempExtrudeBlock.scaleY',(fra)*storeLongSide*5)
                    
            else:
                if state == 1:
                    mc.setAttr('tempExtrudeBlock.scaleX',(fra))
                    mc.setAttr('tempExtrudeBlock.scaleY',(fra))
                elif state == 2:
                    mc.setAttr('tempExtrudeBlock.scaleX',(fra))
                    mc.setAttr('tempExtrudeBlock.scaleZ',(fra))
                else:
                    mc.setAttr('tempExtrudeBlock.scaleX',(fra))
                    mc.setAttr('tempExtrudeBlock.scaleY',(fra))
            screenX = vpX
            mc.refresh(cv=True,f=True)
    elif(modifiers == 5):
       if mc.objExists('cutCircleContral'):
            if screenX > vpX:
                storeCutCircleS = storeCutCircleS - 0.2
            else:
                storeCutCircleS = storeCutCircleS + 0.2
            seg = int(storeCutCircleS)
            if seg < 3:
                seg = 3
            elif seg >50:
                seg = 50
            mc.setAttr('cutCircleContral.subdivisionsAxis',(seg))
            screenX = vpX
            mc.refresh(cv=True,f=True)
    elif(modifiers == 13):
        screenX = vpX
        screenY = vpY
        pos = om.MPoint()
        dir = om.MVector()
        omui.M3dView().active3dView().viewToWorld(int(vpX), int(vpY), pos, dir)
        pos2 = om.MFloatPoint(pos.x, pos.y, pos.z)
        hitpoint = om.MFloatPoint()
        hitFace = om.MScriptUtil()
        hitFace.createFromInt(0)
        hitFacePtr = hitFace.asIntPtr()
        intersection = fnMeshA.closestIntersection(
        om.MFloatPoint(pos2),
        om.MFloatVector(dir),
        None,
        None,
        False,
        om.MSpace.kWorld,
        100000,
        False,
        None,
        hitpoint,
        None,
        hitFacePtr,
        None,
        None,
        None)
        if intersection:
            mc.move(hitpoint.x, hitpoint.y, hitpoint.z, 'tempExtrudeBlock' , absolute=True, ws=1)
            mc.refresh(cv=True,f=True)
    
def instCreateInfoPlane():
    global targetMmesh
    global targetMmeshScale
    state = mc.radioButtonGrp('cutPlane', q=1 , sl=1)
    if mc.objExists("cutGirdShader") == 0:
        shader=mc.shadingNode("surfaceShader", name = 'cutGirdShader',asShader=True)
        shading_group= mc.sets(name='cutGirdShaderSG',renderable=True,noSurfaceShader=True,empty=True)
        mc.connectAttr('cutGirdShader.outColor', 'cutGirdShaderSG.surfaceShader',f=1 )
        cutGirdMask = mc.shadingNode('ramp', asTexture=True, name='cutGirdMask')
        cutGirdMask2D = mc.shadingNode('place2dTexture', asUtility=True, name='cutGirdMask2D')
        mc.connectAttr('cutGirdMask2D.outUV', 'cutGirdMask.uv',f=1)
        mc.connectAttr('cutGirdMask.outColor', 'cutGirdShader.outTransparency',f=1)
        cutGirdLine = mc.shadingNode('grid', asTexture=True, name='cutGirdLine')
        cutGirdLine2D = mc.shadingNode('place2dTexture', asUtility=True,name='cutGirdLine2D')
        mc.connectAttr('cutGirdLine2D.outUV', 'cutGirdLine.uv',f=1)
        mc.connectAttr('cutGirdLine.outColor', 'cutGirdShader.outColor',f=1)
        mc.setAttr( "cutGirdLine2D.repeatU",40)
        mc.setAttr( "cutGirdLine2D.repeatV",40)
        mc.setAttr( "cutGirdLine.uWidth",0.05)
        mc.setAttr( "cutGirdLine.vWidth",0.05)
        mc.setAttr( "cutGirdMask.type", 4)
        mc.setAttr( "cutGirdMask.interpolation", 4)
        mc.setAttr( "cutGirdMask.colorEntryList[0].position", 0.15)
        mc.setAttr( "cutGirdMask.colorEntryList[1].position", 0.35)
        mc.setAttr("cutGirdMask.colorEntryList[0].color", 0.9, 0.9, 0.9, type="double3")
        mc.setAttr("cutGirdMask.colorEntryList[1].color", 1, 1, 1, type="double3")
        mc.setAttr("cutGirdLine.lineColor", 0.25, 1, 1, type="double3")
    view = omui.M3dView.active3dView()
    cam = om.MDagPath()
    view.getCamera(cam)
    camPath = cam.fullPathName()
    cameraTrans = mc.listRelatives(camPath,type='transform',p=True)
    ratio = mc.getAttr('defaultResolution.deviceAspectRatio')
    focalLengths = mc.getAttr(cameraTrans[0]+'.focalLength')
    nearClipPlane = mc.getAttr(cameraTrans[0]+'.nearClipPlane')
    #mc.setAttr((cameraTrans[0]+'.nearClipPlane'),0.01)
    if mc.objExists('instCutPlane'):
        mc.delete('instCutPlane')
    nodeNmae = mc.polyPlane(w = 1, h=1 ,sx= 40, sy= 40, ax =(0,0,1), cuv= 2, ch=1)
    mc.rename(nodeNmae[-1], 'instCutPlaneControl')
    mc.rename('instCutPlane')
    mc.setAttr( 'instCutPlane.visibility',0)
    mc.setAttr( 'instCutPlane.receiveShadows',0)
    mc.setAttr( 'instCutPlane.castsShadows',0)
    if state == 1:
        mc.parentConstraint( cameraTrans[0],'instCutPlane',weight =1)
        mc.delete(constraints=True)
        mc.CreateEmptyGroup()
        mc.rename('instCutGrp')
        mc.parentConstraint( cameraTrans[0], 'instCutGrp',weight =1)
        mc.parent('instCutPlane', 'instCutGrp')
        mc.setAttr( 'instCutPlane.translateZ', (-1.05*nearClipPlane))
        head3d = mc.pointPosition('instCutPlane.vtx[0]' )
        tail3d = mc.pointPosition('instCutPlane.vtx[1680]' )
        head2D = worldSpaceToImageSpace(cameraTrans[0], (head3d[0],head3d[1],head3d[2]))
        tail2d = worldSpaceToImageSpace(cameraTrans[0], (tail3d[0],tail3d[1],tail3d[2]))
        distanceX = tail2d[0] -  head2D[0]
        distanceY = tail2d[1] -  head2D[1]
        resWidth,resHeight = screenRes()
        mc.setAttr('instCutPlane.scaleX', (resWidth/distanceX*1.2))
        mc.setAttr('instCutPlane.scaleY', (resWidth/distanceX*1.2))
        mc.setAttr( 'instCutPlane.visibility',1)
    elif state == 2:
        bbox = mc.exactWorldBoundingBox(targetMmesh)
        width = bbox[3] - bbox[0]
        height = bbox[4] - bbox[1]
        depth = bbox[5] - bbox[2]
        longest_edge = max(width, height, depth)
        targetMmeshScale = longest_edge
        mc.setAttr('instCutPlane.scaleX', (longest_edge*1.2))
        mc.setAttr('instCutPlane.scaleY', (longest_edge*1.2))
        mc.CreateEmptyGroup()
        mc.rename('instCutGrp')
        mc.parent('instCutPlane', 'instCutGrp')
        mc.setAttr( 'instCutPlane.translateY', (0.01*longest_edge*0.6))
        mc.setAttr( 'instCutPlane.rotateX',90)
        mc.setAttr("cutGirdLine.lineColor", 1, 1, 0, type="double3")
    else:
        bbox = mc.exactWorldBoundingBox(targetMmesh)
        width = bbox[3] - bbox[0]
        height = bbox[4] - bbox[1]
        depth = bbox[5] - bbox[2]
        longest_edge = max(width, height, depth)
        targetMmeshScale = longest_edge
        mc.setAttr('instCutPlane.scaleX', (longest_edge*1.2))
        mc.setAttr('instCutPlane.scaleY', (longest_edge*1.2))
        mc.CreateEmptyGroup()
        mc.rename('instCutGrp')
        mc.parent('instCutPlane', 'instCutGrp')
        mc.setAttr( 'instCutPlane.translateY', (0.01*longest_edge))
        mc.setAttr("cutGirdLine.lineColor", 1, 1, 0, type="double3")  
        mc.setAttr( 'instCutPlane.visibility',1)
        
    mc.select('instCutPlane')
    mc.hyperShade(assign="cutGirdShader") 
    mc.select(cl=1)
    model_panels = mc.getPanel(type='modelPanel')
    state = mc.radioButtonGrp('cutPlaneDisp', q=1, sl=1)
    if state == 1:
        for m in model_panels:
            mc.modelEditor(m, e=1, displayTextures=1)
        mc.setAttr("instCutPlaneShape.template", 0)
    else:
        for m in model_panels:
            mc.modelEditor(m, e=1, displayTextures=0)
        mc.setAttr("instCutPlaneShape.template", 1)

def cutGridUIConnect():
    state = mc.radioButtonGrp('cutPlane', q=1 , sl=1)
    if state == 1:
        mc.connectControl( 'cutGridRot', 'instCutPlane.rotateZ')
    elif state == 2:
        mc.connectControl( 'cutGridRot', 'instCutPlane.rotateY')
    else:
        mc.connectControl( 'cutGridRot', 'instCutPlane.rotateZ')
        
    if not mc.attributeQuery('curGridSizeLink', node = 'instCutPlane', ex=True ):
        mc.addAttr('instCutPlane', longName='curGridSizeLink', attributeType='long', defaultValue=0)
        mc.setAttr('instCutPlane.curGridSizeLink', e=True, keyable=True)
    if not mc.attributeQuery('curGridVisLink', node = 'instCutPlane', ex=True ):
        mc.addAttr('instCutPlane', longName='curGridVisLink', attributeType='long', defaultValue=0)
        mc.setAttr('instCutPlane.curGridVisLink', e=True, keyable=True)
    mc.connectControl( 'cutGridSize', 'instCutPlane.curGridSizeLink')
    mc.connectControl( 'cutGridVis', 'instCutPlane.curGridVisLink')
    if mc.objExists("cutGridExp"):
        mc.delete("cutGridExp")
    
    expression_string = """
    cutGirdMask.colorEntryList[1].position = (instCutPlane.curGridVisLink * 0.1) + 0.35;
    cutGirdLine2D.repeatU = instCutPlane.curGridSizeLink + 1;
    cutGirdLine2D.repeatV = instCutPlane.curGridSizeLink + 1;
    instCutPlaneControl.subdivisionsWidth = instCutPlane.curGridSizeLink + 1;
    instCutPlaneControl.subdivisionsHeight = instCutPlane.curGridSizeLink + 1;
    float $newX = instCutPlane.curGridSizeLink * 0.00125;
    if ($newX > 0.05) {
        cutGirdLine.uWidth = 0.05;
        cutGirdLine.vWidth = 0.05;
    } else {
        cutGirdLine.uWidth = $newX;
        cutGirdLine.vWidth = $newX;
    }
    float $VisX = (instCutPlane.curGridVisLink * 0.1) + 0.35;
    if ($VisX < 0.5) {
        cutGirdMask.colorEntryList[1].position = 0.35;
    } 

    """
    mc.expression(s=expression_string, o='instCutPlane', ae=True, uc='all',n='cutGridExp')
    mc.setAttr("instCutPlane.curGridSizeLink",40)
    if not mc.objExists('cutGirdLayer'):
        mc.createDisplayLayer(name = ('cutGirdLayer'))
    mc.editDisplayLayerMembers( ('cutGirdLayer'),'instCutPlane')
    mc.setAttr(('cutGirdLayer.displayType'),2)
    if mc.objExists("instCutGrp"):
        mc.setAttr('instCutGrp.hiddenInOutliner',1)
        
def cutGridDispSwitch():
    model_panels = mc.getPanel(type='modelPanel')
    if mc.objExists("instCutPlane"):
        state = mc.radioButtonGrp('cutPlaneDisp', q=1, sl=1)
        if state == 1:
            for m in model_panels:
                mc.modelEditor(m, e=1, displayTextures=1)
            mc.setAttr("instCutPlaneShape.template", 0)
        else:
            for m in model_panels:
                mc.modelEditor(m, e=1, displayTextures=0)
            mc.setAttr("instCutPlaneShape.template", 1)
        mc.refresh(cv=True,f=True)
    mc.setFocus("MayaWindow")  
        
def cutGridTypeSwitch():
    if mc.objExists("cutBlockShader"):
        cutMode = mc.radioButtonGrp('cutMode', q=1, sl=1)
        if cutMode == 1:
            mc.setAttr("cutBlockShader.outColor", 0.65, 0, 0.85, type="double3")
        else:
            mc.setAttr("cutBlockShader.outColor", 0, 1, 0.2, type="double3")
    mc.setFocus("MayaWindow")
    
def cutPlaneSwitch():   
    cleanList = ('instCutPlane','extudeCluster','tempExtrudeBlock','instCut*','blockFizMesh')
    for c in cleanList:
        if mc.objExists(c):
            mc.delete(c)
    mc.setToolTo('selectSuperContext')
    mc.setFocus("MayaWindow")
    
def resetPanelFocus():
    mc.setFocus("MayaWindow")
      
def cutGoDraw():
    global cutType 
    cutType = 1
    cutGo()

def cutGoBox():
    global cutType 
    cutType = 2
    cutGo()

def cutGoCircle():
    global cutType 
    cutType = 3
    cutGo()
    
def cutGo():
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    if beseMesh:
        mc.scriptEditorInfo(suppressWarnings=1,suppressInfo=0,se=0)
        global targetMmesh
        global cameraUsed
        global cutType 
        state = mc.radioButtonGrp('cutPlane', q=1, sl=1)
        targetMmesh = (beseMesh + '_bool')
        #mc.button('instCutGo', e=1,en=0)
        mc.radioButtonGrp('cutPlane', e=1,en=0)
        hideAllCutter()
        if state == 1:
            cut2DGo()
        elif state == 2:
            cut3DGo()
        else:
            orthoCam()
        mc.iconTextButton('cutGoDrawButton',e=1, en=0)
        mc.iconTextButton('cutGoBoxButton',e=1, en=0)
        mc.iconTextButton('cutGoCircleButton',e=1, en=0)
    
def orientCutter(orientation):
    checkButtonStateList = ['surfOrientButton','objOrientButton', 'worldOrientButton']
    for c in checkButtonStateList:
        buttonState = mc.button( c , e=1,  bgc = [0.28,0.28,0.28] )
    if orientation == 'surface':
        buttonState = mc.button('surfOrientButton',e=1,  bgc = [0.3,0.5,0.6] )
    elif orientation == 'object':
        buttonState = mc.button('objOrientButton' ,e=1,  bgc = [0.3,0.5,0.6] )
    elif orientation == 'world':
        buttonState = mc.button('worldOrientButton' ,e=1,  bgc = [0.3,0.5,0.6] )
    #selList = mc.ls(sl=1,fl=1)
    #if selList:
    #    for s in selList:
    #        if 'boxCutter' in s:
    #            applyOrientCutter()
                
  
def applyOrientCutter():
    checkButtonStateList = ['surfOrientButton','objOrientButton', 'worldOrientButton']
    getCurrentOrient = ''
    for c in checkButtonStateList:
        buttonState = mc.button( c ,q=1,  bgc = True )
        if buttonState[1] > 0.4:
            getCurrentOrient = c
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    getCutters = mc.ls((beseMesh+'_cutterGrp|boxCutter*'), type = 'transform', l=True, sl = True)
    for g in getCutters:
        if getCurrentOrient == 'surfOrientButton': # orient to face
            cutterPos = om.MPoint(mc.getAttr(g+'.translateX'), mc.getAttr(g+'.translateY'), mc.getAttr(g+'.translateZ'))
            hitpoint = om.MFloatPoint()
            hitFacePtr = om.MScriptUtil().asIntPtr()
            snapMesh = (beseMesh +'_boolShape')
            selectionList = om.MSelectionList()
            selectionList.add(snapMesh)
            dagPath = om.MDagPath()
            selectionList.getDagPath(0, dagPath)
            fnMesh = om.MFnMesh(dagPath)
            objPos = om.MPoint(mc.getAttr(beseMesh+'.translateX'), mc.getAttr(beseMesh+'.translateY'), mc.getAttr(beseMesh+'.translateZ'))
            dirVec = om.MVector(objPos - cutterPos).normal()
            intersection = fnMesh.closestIntersection(om.MFloatPoint(cutterPos.x, cutterPos.y, cutterPos.z), om.MFloatVector(dirVec), None, None, False, om.MSpace.kWorld, 99999, False, None, hitpoint, None, hitFacePtr, None, None, None)
            if intersection:
                hitFace = om.MScriptUtil(hitFacePtr).asInt()
                hitFaceName = (snapMesh + '.f[' + str(hitFace) +']')
                rx, ry, rz = getFaceAngle(hitFaceName)
                mc.setAttr(g+'.rotateX', rx)
                mc.setAttr(g+'.rotateY', ry)
                mc.setAttr(g+'.rotateZ', rz)
        elif getCurrentOrient == 'objOrientButton': # orient to target mesh orientation
            mc.setAttr(g+'.rotateX', mc.getAttr(beseMesh+'.rotateX'))
            mc.setAttr(g+'.rotateY', mc.getAttr(beseMesh+'.rotateY'))
            mc.setAttr(g+'.rotateZ', mc.getAttr(beseMesh+'.rotateZ'))
        elif getCurrentOrient == 'worldOrientButton': # just zero out rotation
            mc.setAttr(g+'.rotateX', 0.0)
            mc.setAttr(g+'.rotateY', 0.0)
            mc.setAttr(g+'.rotateZ', 0.0)

def cut3DGo():
    global extrudeNewMesh
    extrudeNewMesh = []
    global oldShader
    global camPivot
    global cameraTrans
    global clickNo
    clickNo = 0
    global fnMeshA
    global targetMmesh
    global cutToolID
    global recordAlignAngle
    recordAlignAngle = 0
    global recordHitFaceName
    recordHitFaceName = []

    cleanList = ('extudeCluster','tempExtrudeBlock','cutBlockShader','blockFizMesh')
    for c in cleanList:
        if mc.objExists(c):
            mc.delete(c)
    if targetMmesh:
        shape_nodes = mc.listRelatives(targetMmesh, shapes=True, fullPath=True)
        oldShader = mc.listConnections(shape_nodes, type='shadingEngine')[0]
        if mc.objExists('instCutGrp') == 0:
            instCreateInfoPlane()
            cutGridUIConnect()
        mc.setAttr("cutGirdLine.lineColor", 1, 1, 0, type="double3")
        model_panels = mc.getPanel(type='modelPanel')
        for m in model_panels:
            state = mc.isolateSelect(m, q=1, s =1)
            if state:
                mc.isolateSelect(m, addDagObject= 'instCutGrp' )
        view = omui.M3dView.active3dView()
        cam = om.MDagPath()
        view.getCamera(cam)
        camPath = cam.fullPathName()
        cameraTrans = mc.listRelatives(camPath,type='transform',p=True)
        camPivot = mc.xform(cameraTrans, q=1, ws=1, rp=1)
        if mc.objExists('instCutPlane'):
            selectionList = om.MSelectionList()
            selectionList.add('instCutPlane')
            dagPath = om.MDagPath()
            selectionList.getDagPath(0, dagPath)
            fnMeshA = om.MFnMesh(dagPath)
            global ctxPlane
            ctxPlane = 'drawPlane'
            if mc.draggerContext(ctxPlane, exists=True):
                mc.deleteUI(ctxPlane)
            mc.draggerContext(ctxPlane, pressCommand = planeClick, dragCommand = planeDrag, name=ctxPlane, cursor='crossHair',undoMode='step')
            mc.setToolTo(ctxPlane)
            mc.scriptJob(runOnce=True, event=["ToolChanged", cut3DDraw])

def cut3DExtrude():
    if mc.objExists("tempExtrudeBlock"):
        face_count = mc.polyEvaluate('tempExtrudeBlock', face=True)
        if face_count > 1:
            getLarge = getLargeAreaFace()
            allFace = mc.ls('tempExtrudeBlock.f[*]',fl=1)
            allFace.remove(getLarge)
            mc.delete(allFace)
        cutPlanePivot = mc.xform('instCutPlane', q=1, ws=1, rp=1)
        global targetMmesh
        global extrudeNewMesh
        global targetMmeshScale
        global curExtrudeCount
        global recordHitPoint
        recordHitPoint = [0,0,0]
        curExtrudeCount = 0.1 * targetMmeshScale
        normal1 = get_face_normal('instCutPlane', 0)
        normal2 = get_face_normal('tempExtrudeBlock', 0)
        normal1.normalize()
        normal2.normalize()
        dot_product = normal1 * normal2
        if dot_product > 0:
            pass
        else:
            mc.polyNormal('tempExtrudeBlock', normalMode=0, userNormalMode=0, ch=0)
        mc.select('tempExtrudeBlock')
        extrudeNode = mc.polyExtrudeFacet(constructionHistory=1, keepFacesTogether=1, divisions=1, twist=0, taper=1, off=0, thickness=curExtrudeCount, smoothingAngle=30)
        mc.rename(extrudeNode,'cutExtrudeNode')
        mc.select('tempExtrudeBlock')
        useOwnCutterShape()
        global ctxExtrude
        ctxExtrude = 'extrudePlane'
        if mc.draggerContext(ctxExtrude, exists=True):
            mc.deleteUI(ctxExtrude)
        mc.draggerContext(ctxExtrude, pressCommand = extrudeClick, dragCommand = extrudeDrag, name=ctxExtrude, cursor='crossHair',undoMode='step')
        mc.setToolTo(ctxExtrude)
        mc.scriptJob(runOnce=True, event=["ToolChanged", extrudeEndCut])

def extrudeEndCut():
    checCurrentkHUD =  mc.headsUpDisplay(lh=1)
    if checCurrentkHUD is not None:
        for t in checCurrentkHUD:
            if 'HUDBevelStep' in t:
                mc.headsUpDisplay(t, rem=1)
    global targetMmesh 
    global cutType 
    currentCutter = mc.ls(sl=1,fl=1)
    if cutType == 1:
        mc.parent(currentCutter[0],'instCutGrp')
    elif cutType == 2:
        mc.parent(currentCutter[0],'cutBoxMoveGrp')
    else:
        mc.parent(currentCutter[0],'instCutGrp')
    mc.makeIdentity(currentCutter[0], apply=True, translate=True, rotate=True, scale=True, normal=False, preserveNormals=True)
    mc.delete(ch=1)
    beseMesh = mc.optionMenu('baseMeshMenu', query = True, v = True)
    mc.parent(currentCutter[0], beseMesh + '_cutterGrp')
    mc.CenterPivot()
    cleanList = ('extudeCluster','tempExtrudeBlock','cutBlockShader','blockFizMesh','cutBoxMoveGrp','cutBoxMoveA')
    for c in cleanList:
        if mc.objExists(c):
            mc.delete(c)
    mc.CenterPivot()
    mc.setToolTo('moveSuperContext')
    currnet = mc.ls(sl=1,fl=1)[0]
    mc.setAttr(currnet + '.hiddenInOutliner',0)
    mc.setAttr(currnet + '.template', 0)
    mc.radioButtonGrp('cutPlane', e=1,en=1)
    mc.iconTextButton('cutGoDrawButton',e=1, en=1)
    mc.iconTextButton('cutGoBoxButton',e=1, en=1)
    mc.iconTextButton('cutGoCircleButton',e=1, en=1)
    checkAuto = mc.checkBox('autoOffP', q=1,v=1 )
    if checkAuto == 1:
        cutGridReset()
    mc.setToolTo('moveSuperContext')
    
def howInstructions():
    if mc.window("instructionsWindow", exists=True):
        mc.deleteUI("instructionsWindow", window=True)
    window = mc.window("instructionsWindow", title="How to Use", widthHeight=(640, 470), sizeable=0 ,mxb = False,mnb = False)
    mc.columnLayout(adjustableColumn=True)
    instructions = '''
    1. After press icon, A yellow grid will be shown; 
        2D mode, this is the time to adjust the camera angle.
        3D/OrthoGraphic mode, click and drag yellow grid on the model.
    
    2. Adjust grid size, rotation, and visibility via UI.
    
    3. Change tool (e.g., press w key to switch translate tool).
    
    4. The camera angle will be locked, a blue grid will show, and it will enter drawing mode.
    
    5. Adjust grid size, rotation, and visibility via UI if required.
    
    6. Start drawing shape.
    
        Snap grid: Hold CTRL, then mouse drag.
        
        Bevel last corner: Hold SHIFT, then mouse click.
        Adjust Segment: While holding SHIFT, press CTRL together, then mouse drag.
        Adjust Fraction: While holding SHIFT and CTRL (adjust segment), release SHIFT (only hold CTRL), then mouse drag.
    
        Bevel all corners: Hold SHIFT and CTRL together, then mouse click.
        Adjust Segment: Hold SHIFT and CTRL, then mouse drag.
        Adjust Fraction: While holding SHIFT and CTRL (adjust segment), release SHIFT (only hold CTRL), then mouse drag.
    
        Move draw region: Hold SHIFT, CTRL, and ALT together, then mouse drag.
    
    7. Change tool to finish the cut (e.g., press W key to switch translate tool).
    
    8. Use mouse drag to adjust cutter length for 3D/OrthoGraphic mode.
    9. Press Reset button to dismiss drawing grid
             
    *** any unexpected error, press Reset button,
          nodes may not clean when tool is terminated in middle of the process.
    
    '''
    mc.text(label=instructions, align="left", wordWrap=True)
    mc.showWindow(window)

def dockSpeedCut():
    dock = mc.workspaceControl("jwSpeedCutDock", e=1 ,dockToMainWindow=("right", 0))


def SCUI(state):
    mayaHSize = mc.window('MayaWindow', q=1, h=1)
    dockState = mc.workspaceControl("jwSpeedCutDock", q=1,fl=1)
  
    frameList = {'meshSetupFrame','meshSymmetryFrame','meshRadialMirrorFrame','cutterFrame','controlFrame','alignmentFrame','patternFrame','bakeFrame','meshBevelManagerFrame'}
    midList = {'meshSetupFrame','cutterFrame','controlFrame'}
    otherList = list(set(frameList) - set(midList))
    if state == 'min':
        newH = mayaHSize    
        for f in frameList:
            mc.frameLayout(f, e=1, cl= 1)
        if dockState == 1:
            mc.window("jwSpeedCutDock", e=True, height=210,w=320)    
            mc.scrollLayout('SCScrol',e=1 , h=210)
        else:
            mc.scrollLayout('SCScrol',e=1 , h=newH)
        

    elif state == 'mid':
        newH = mayaHSize   
        for m in midList:
            mc.frameLayout(m, e=1, cl= 0)
        for o in otherList:
            mc.frameLayout(o, e=1, cl= 1)
        if dockState == 1:
            mc.window("jwSpeedCutDock", e=True, height=940,w=320)    
            mc.scrollLayout('SCScrol',e=1 , h=940)
        else:
            mc.scrollLayout('SCScrol',e=1 , h=newH)
        
    elif state == 'max':
        newH = mayaHSize*.90    
        for f in frameList:
            mc.frameLayout(f, e=1, cl= 0)
        if dockState == 1:
            mc.window("jwSpeedCutDock", e=True, height=newH,w=330)    
        mc.scrollLayout('SCScrol',e=1 , h=newH)

def jwSpeedCutUI():
    if mc.workspaceControl("jwSpeedCutDock", exists=True):
        mc.deleteUI("jwSpeedCutDock")

    dock = mc.workspaceControl(
        "jwSpeedCutDock",
        label="speedCut 2.24",
        iw = 320,
        dockToMainWindow=("right", 1),
        retain=False,
    )
    mayaHSize = mc.window('MayaWindow', q=1, h=1)
    mc.tabLayout(tv = 0)
    mc.columnLayout(adj=1)
    mc.rowColumnLayout(nc= 5 ,cw=[(1,170),(2,30),(3,30),(4,30),(5,30)])
    mc.text(l ='')
    mc.iconTextButton(l= '--',st = 'textOnly', c = 'SCUI("min")')
    mc.iconTextButton(image1= 'shelfTab.png', c = 'SCUI("mid")')
    mc.iconTextButton(image1= 'menu_key.png', c = 'SCUI("max")')
    mc.iconTextButton(image1= 'hsShowRightTabsOnly.png', c = 'dockSpeedCut()', h=20)
    mc.setParent( '..' )
    mc.scrollLayout('SCScrol',h=mayaHSize)
    mc.columnLayout()
    mc.frameLayout('meshSetupFrame', cll= 1, cl= 0, label= "Mesh Setup" ,  bgc =[0.2,0.28,0.28] , w= 300)
    mc.text(l ='',h=1)
    mc.rowColumnLayout(nc= 6 ,cw=[(1,35),(2,120),(3, 5),(4,60),(3, 5),(6,60)])
    mc.text(l ='  Mesh')
    mc.optionMenu('baseMeshMenu',  bgc =[0.24,0.24,0.24], bsp ='checkBaseMeshList()' ,cc='loadSymmetryState(),cageVisToggle(),showAllCutter(),updateVisLayer(),updateSnapState(),fadeOutCage(),rdMirrorUIUpdate()')
    mc.menuItem("NoBaseMeshMenu", label='No Base Mesh' )
    mc.text(l ='')
    mc.button('setBaseButton', l= "Set", c = 'checkBaseMeshList(),setCutterBaseMesh(),baseMeshColorUpdate(),updateVisLayer()' ,  bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('reTargetButton', l= "reTarget", c = 'reTarget()',  bgc = [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.rowColumnLayout(nc= 10,cw=[(1,50),(2,30),(3,5),(4,30),(5,5),(6,30),(7,30),(8,42),(9, 5),(10,60)])
    mc.text(l ='')
    mc.iconTextButton('meshLayerButton', h = 25, w = 30,  c = 'toggleLayer()', style='iconOnly', image1= 'nodeGrapherModeAll.svg' )
    mc.text(l ='')
    mc.iconTextButton('meshColorUpdateButton', h = 25, w = 30,  c = 'baseMeshColorBase()', style='iconOnly', image1= 'colorConstant.png' )
    mc.text(l ='')
    mc.iconTextButton('meshColorBaseButton', h = 25, w = 30,  c = 'baseMeshColorUpdate()', style='iconOnly', image1= 'ramp.svg' )
    mc.text(l ='')
    mc.checkBox('finalAll', label= "All" ,v=0)
    mc.text(l ='')
    mc.button('freeResultButton', l= "Finalize", c = lambda *_: freeResultMesh(),  bgc = [0.28,0.28,0.28] )
    mc.text(l ='',h=3)
    mc.setParent( '..' )
    mc.setParent( '..' )
    ####################################################################################################################################################################################### 
    mc.frameLayout('bakeFrame',cll= 1, cl= 1, label= "Bake" ,  bgc =  [0.2,0.28,0.28]  , w= 300)
    mc.text(l ='',h=1)
    mc.rowColumnLayout(nc=6, cw=[(1,40),(2,80),(3,5),(4,80),(5,5),(6,80)])
    mc.text(l ='',h=10)
    mc.button('bakeUnSelButton', w = 50,   l= "Unselect", c = lambda *_: bakeCutter('unselect'), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('bakeAllButton', w = 50,   l= "All", c = lambda *_: bakeCutter('all'),bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('bakeRestoreButton', w = 50,  l= "Restore",c = 'restoreCutterWithSymmtry()',bgc = [0.28,0.28,0.28] )
    mc.text(l ='',h=3)
    mc.setParent( '..' )
    mc.setParent( '..' )
    #######################################################################################################################################################################################
    mc.frameLayout('meshSymmetryFrame', cll= 1, cl= 1, label= "Mesh Symmetry" ,   bgc = [0.2,0.28,0.28] , w= 300)
    buttonSize = 25
    mc.text(l ='',h=1)
    mc.rowColumnLayout(nc=10 ,cw=[(1,70),(2,buttonSize),(3,buttonSize),(4,buttonSize),(5, buttonSize),(6,buttonSize),(7,buttonSize),(8,buttonSize),(9,buttonSize),(10,buttonSize)])
    mc.text(l ='      Direction')
    mc.text(l ='X')
    mc.button('symmXButtonP', l= "-", c ='boolSymmetry("x"' + ' ,1)' , bgc = [0.28,0.28,0.28])
    mc.button('symmXButtonN', l= "+", c ='boolSymmetry("x"' + ' ,2)' , bgc = [0.28,0.28,0.28])
    mc.text(l ='Y')
    mc.button('symmYButtonP', l= "-", c ='boolSymmetry("y"' + ' ,1)' , bgc = [0.28,0.28,0.28])
    mc.button('symmYButtonN', l= "+", c ='boolSymmetry("y"' + ' ,2)' , bgc = [0.28,0.28,0.28])
    mc.text(l ='Z')
    mc.button('symmZButtonP', l= "-", c ='boolSymmetry("z"' + ' ,1)' , bgc = [0.28,0.28,0.28])
    mc.button('symmZButtonN', l= "+", c ='boolSymmetry("z"' + ' ,2)' , bgc = [0.28,0.28,0.28])
    mc.setParent( '..' )
    mc.rowColumnLayout(nc=6,cw=[(1,80),(2,104),(3, 6),(4,104)])
    mc.text(l ='')
    mc.button( l= "Reset", c ='boolSymmetryReset()', bgc =  [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button( l= "Freeze", c ='boolSymmetryFreeze()', bgc =  [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.rowColumnLayout(nc=6,cw=[(1,70),(2,75),(3,30),(4,57),(5,12),(6,50)])
    mc.text(l ='      Cage')
    mc.colorSliderGrp('CageColorSlider', l= '',cw = [(1,2),(2,13)], rgb=(0.5, 0, 0) ,dc = 'updateCageColor()')
    mc.iconTextButton(en = 1, w = 30,  style='iconOnly',image1='eye.png' )
    mc.floatSlider('CageTransparentSlider',min=0.1, max=1, value=0.5, step = 0.1 ,dc = 'updateCageTransparent()')
    mc.text(l ='')
    mc.button( l= 'On/Off', w = 35, bgc = [0.28,0.28,0.28],c='cageVisToggle()')
    mc.text(l ='',h=3)
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.frameLayout('meshRadialMirrorFrame', cll= 1, cl= 1, label= "Mesh Radial Mirror" ,   bgc = [0.2,0.28,0.28] , w= 300)
    mc.text(l ='',h=1)
    mc.rowColumnLayout(nc=9 ,cw=[(1,70),(2,40),(3,40),(4,40),(5, 5),(6, 60),(7,20),(8,20)])
    mc.text(l ='Axis')
    mc.button('rMirrorXButton', l= "X", c ='rdMirror("x")' , bgc = [0.28,0.28,0.28])
    mc.button('rMirrorYButton', l= "Y", c ='rdMirror("y")' , bgc = [0.28,0.28,0.28])
    mc.button('rMirrorZButton', l= "Z", c ='rdMirror("z")' , bgc = [0.28,0.28,0.28])
    mc.text(l ='')
    mc.text(l ='Half')
    mc.button('rMirrorNegButton', l= "-", c ='rdMirrorHalf("n")' , bgc = [0.28,0.28,0.28])
    mc.button('rMirrorPosButton', l= "+", c ='rdMirrorHalf("p")' , bgc = [0.28,0.28,0.28])
    mc.setParent( '..' )
    mc.rowColumnLayout(nc=3 ,cw=[(1,240),(2,15),(3,40)])
    mc.intSliderGrp('rMirrorSideSlider',  v = 1,   min = 3 ,  max = 15,  fmx = 20, s = 1, cw3 = [70,40,30] , label = "Side        " ,field =True ,cc= 'rdMirrorUpdate()',dc= 'rdMirrorUpdate()')
    mc.text(l ='')
    mc.text(l ='')
    mc.intSliderGrp('rMirrorOffsetSlider',  v = 10,   min = -20 ,  max = 20, fmn = -200, fmx = 200, s = 1, cw3 = [70,40,30] , label = "Offset        " ,field =True ,cc= 'rdMirrorOffsetUpdate()',dc= 'rdMirrorOffsetUpdate()')
    mc.text(l ='')
    mc.button(l= "Done", c ='rdMirrorOutput()' , bgc = [0.28,0.28,0.28])
    mc.text(l ='',h=3)
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.setParent( '..' )
    #######################################################################################################################################################################################
    mc.frameLayout('cutterFrame', cll= 1, cl= 0, label= "Cutter" ,  bgc = [0.5 , 0.41 , 0.05] , w= 300)
    mc.text(l ='',h=1)
    mc.rowColumnLayout(nc=8 ,cw=[(1,40),(2, 58),(3,5),(4, 58),(5,5),(6,58),(7,5),(8,58)])
    mc.text(l ='Show',h=20)
    mc.button(w=40, l= "Selected",  c = 'hideUnSelectedCutters()', bgc = [0.28,0.28,0.28])
    mc.text(l ='')
    mc.button( w = 40, l= "All", c = 'showAllCutter()', bgc = [0.28,0.28,0.28])
    mc.text(l ='')
    mc.button( w = 40,  l= "None", c = 'hideAllCutter()', bgc = [0.28,0.28,0.28])
    mc.text(l ='',h=20)
    mc.button( w = 40,  l= "Loop",  c = 'showLastCutter()', bgc = [0.28,0.28,0.28])
    mc.setParent( '..' )
    mc.columnLayout()
    mc.rowColumnLayout(nc=8 ,cw=[(1,40),(2, 58),(3,5),(4, 58),(5,5),(6,58),(7,5),(8,58)])
    mc.text(l ='Orient',h=10)
    mc.button('surfOrientButton', w = 25, l= "Surface", c = 'orientCutter("surface")', bgc = [0.3, 0.5, 0.6] )
    mc.text(l ='')
    mc.button('objOrientButton', w = 25, l= "Object", c = 'orientCutter("object")', bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('worldOrientButton', w = 25, l= "World", c = 'orientCutter("world")', bgc = [0.28,0.28,0.28] )
    #mc.text(l ='')
    #mc.button(w = 75, l= "Set Selected", c = 'applyOrientCutter()', bgc = [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.columnLayout()
    mc.floatSliderGrp('cutterScaleSlider',  v = 1, min = 0.1, max = 5,  s = 0.1, cw3 = [40,50,190] , label = "Scale  " ,field =True)
    mc.floatField( 'cuterPreSize' , value=1 ,vis=0 )
    mc.setParent( '..' )
    mc.rowColumnLayout(nc=8, cw=[(1,40),(2,58),(3,5),(4,58),(5,5),(6,58),(7,5),(8,58)])
    mc.text(l ='Opera',h=10)
    mc.button('subsButton',  l= "Difference", c = 'cutterType("subs")', bgc = [0.3, 0.5, 0.6] )
    mc.text(l ='')
    mc.button('unionButton', l= "Union", c ='cutterType("union")', bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('cutButton', l= "After Cut", c ='cutterType("cut")', bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('cutToNewMeshButton', l= "New Grp", c ='cutter2NewMeshGrp()', bgc = [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.separator(height= 10, style= 'in')
    mc.columnLayout()
    mc.rowColumnLayout(nc=8, cw=[(1,40),(2,58),(3,5),(4,58),(5,5),(6,58),(7,5),(8,58)])
    mc.text(l =' Cutter')
    mc.button('newCutButton', h= 23 ,w = 50, l= "Box", c = 'goPressCutter(4)', bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('triButton', w = 30,   l= "3",  c = 'goPressCutter(3)', bgc = [0.28,0.28,0.28])
    mc.text(l ='')
    mc.button('pentaButton', w = 30, l= "5",  c = 'goPressCutter(5)', bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('hexButton', w = 30,   l= "6",  c = 'goPressCutter(6)', bgc = [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.rowColumnLayout(nc=8, cw=[(1,40),(2,58),(3,5),(4,121),(5,5),(6,58),(7,5),(8,58)])
    mc.text(l ='')
    mc.button('drawCutButton', h= 23 ,w = 50,   l= "Draw", c = 'goDraw()', bgc = [0.28,0.28,0.28])
    mc.text(l ='')
    mc.button('selCutButton', w = 121,   l= "use Selected",  c = 'useOwnCutterShape()', bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('cornerCutButton', h= 23 ,w = 50,  l= "Corner", c = 'goCornerTool()', bgc = [0.28,0.28,0.28])
    mc.text(l ='')
    mc.intSliderGrp('cutterSideSlider', en=1,  vis = 0, v = 4,   min = 3,    max = 6, s = 1, cw3 = [35,40,200] , label = "side  " ,field =True )
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.rowColumnLayout(nc= 2 ,cw=[(1,220),(2,80)])
    mc.rowColumnLayout(nc= 2 ,cw=[(1,40),(2,250)])
    mc.text(l='Plane ')
    mc.radioButtonGrp('cutPlane', nrb=3, sl=1, labelArray3=['2D', '3D', 'OrthoG'], cw = [(1,50),(2,50),(3,90)],cc='cutPlaneSwitch()')
    mc.setParent("..")
    mc.rowColumnLayout(nc= 2 ,cw=[(1,7),(2,58)])
    mc.text(l='',h=5)
    mc.button('instGridReset', l= "Reset", c = 'cutGridReset()',bgc = (0.28,0.28,0.28 ))
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.rowColumnLayout(nc= 10 ,cw=[(1,5),(2,30),(3,15),(4,30),(5,15),(6,30),(7,15),(8,30),(9,95),(10,20)])
    mc.text(l='')
    mc.text(l='Type')
    mc.text(l='')
    mc.iconTextButton('cutGoDrawButton',image1= 'pencil.png', c = 'cutGoDraw()')
    mc.text(l='')
    mc.iconTextButton('cutGoBoxButton',image1= 'cube.png', c = 'cutGoBox()')
    mc.text(l='')
    mc.iconTextButton('cutGoCircleButton',image1= 'cylinder.png', c = 'cutGoCircle()')
    mc.text(l='')
    mc.button('instCutHelpB', l= "?", c = 'howInstructions()', bgc = (0.28,0.28,0.28 ))
    mc.setParent( '..' )
    
    ##########################################################################################################################################################################
    mc.rowColumnLayout(nc= 2 ,cw=[(1,5),(2,290)])
    mc.text(l='')
    mc.intSliderGrp("cutGridSize", v=40, min= 30, max=80 ,fmn = 1, fmx = 200,  s=1, cw3=[30, 40, 0], label="Size   ", field=True, dc='resetPanelFocus()')
    mc.text(l='')
    mc.intSliderGrp("cutGridRot", v=0, min=-45, max=45, s=1, cw3=[30, 40, 0], label="Rot   ", field=True, dc='resetPanelFocus()')
    mc.text(l='')
    mc.intSliderGrp("cutGridVis", v=5, min=1, max=10, s=1, cw3=[30, 40, 0], label="Vis   ", field=True, dc='resetPanelFocus()')
    mc.setParent("..")
    mc.rowColumnLayout(nc= 42 ,cw=[(1,40),(2,150),(3,15),(4,150)])
    mc.text(l='Disp ')
    mc.radioButtonGrp('cutPlaneDisp', nrb=2, sl=1, labelArray2=['Shader', 'Wire'], cw = [(1,70),(2,70)],cc='cutGridDispSwitch()')
    mc.text(l=' ')
    mc.checkBox('autoOffP', label= "AutoOff" ,v=1)
    mc.setParent("..")
    mc.separator(height= 2, style= 'in')
    mc.columnLayout()
    mc.rowColumnLayout(nc=6 ,cw=[(1,40),(2, 80),(3,5),(4, 80),(5,5),(6,80)])
    mc.text(l ='Mirror',h=10)
    mc.button( w = 50, l= "X", c = lambda *_: cutterMirror('x'), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button(w = 50, l= "Y", c = lambda *_: cutterMirror('y'), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button(w = 50, l= "Z", c = lambda *_: cutterMirror('z'), bgc = [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.text(l ='',h=5)
    mc.rowColumnLayout(nc=6 ,cw=[(1,40),(2, 80),(3,5),(4, 80),(5,5),(6,80)])
    mc.text(l ='Edit',h=10)
    mc.button('dulCutButton',   l= "Duplicate", c = lambda *_: cutterDulpicate(), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('comCutButton',   l= "Combine",  c = lambda *_: combineSelCutters(), bgc = [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.text(l ='',h=3)
    mc.setParent( '..' )
    mc.setParent( '..' )
    ########################################################################################################################################################################
    mc.frameLayout('controlFrame',cll= 1, cl= 0, label= "Control" , bgc = [0.5 , 0.41 , 0.05]  , w= 300)
    mc.text(l ='',h=1)
    mc.rowColumnLayout(nc=6, cw=[(1,40),(2,80),(3,5),(4,80),(5,5),(6,80)])
    mc.text(l ='',h=20)
    mc.button( w = 50, l= "Bevel", c = lambda *_: QBoxBevel(), bgc = [0.28,0.28,0.28])
    mc.text(l ='')
    mc.button(w = 50, l= "Smooth", c = lambda *_: QBoxSmooth(),bgc = [0.28,0.28,0.28])
    mc.text(l ='')
    mc.button(w = 50, l= "Remove", c = lambda *_: QBoxBevelRemove(),bgc = [0.28,0.28,0.28])
    mc.setParent( '..' )
    mc.rowColumnLayout()
    mc.columnLayout()
    mc.floatSliderGrp('fractionSlider',  v = 0.2, min = 0.001, max = 1,  s = 0.01, cw3 = [55,40,180] , label = " Fraction" ,field =True,cc = 'attributeFloatSlider("fraction")',dc = 'attributeFloatSlider("fraction")')
    mc.intSliderGrp('segmentsSlider',     v = 1,   min = 1 ,    max = 10,  fmx = 20, s = 1, cw3 = [55,40,180] , label = "Segments" ,field =True ,cc= 'attributeIntSlider("segments")',dc= 'attributeIntSlider("segments")')
    mc.floatSliderGrp('depthSlider',     v = 1,   min = -1 ,   max = 1,   fmn = -3, fmx = 3, s = 1,  cw3 = [55,40,180] , label = "Depth" ,field =True,cc = 'attributeFloatSlider("depth")',dc = 'attributeFloatSlider("depth")')
    mc.setParent( '..' )
    mc.separator(height= 20, style= 'in')
    mc.rowColumnLayout(nc=6, cw=[(1,40),(2,80),(3,5),(4,80),(5,5),(6,80)])
    mc.text(l ='')
    mc.button('makePanelButton', w = 50,  l= "Gap", c = lambda *_: makeGap(),bgc = [0.28,0.28,0.28])
    mc.text(l ='')
    mc.button('ScrapeButton', w = 50,  l= "Scrape", c = lambda *_: scrapeCutter(),bgc = [0.28,0.28,0.28])
    mc.text(l ='')
    mc.button('removePanelButton', w = 50,  l= "Remove", c = lambda *_: removeGap(),bgc = [0.28,0.28,0.28])
    mc.setParent( '..' )
    mc.rowColumnLayout()
    mc.text(l ='',h=3)
    mc.columnLayout()
    mc.floatSliderGrp('gapSlider',   v = 0.3, min = 0.01, max = 5, fmx = 20,  s = 0.01, cw3 = [55,40,180] , label = "Gap   " ,field =True,cc='attributeGapSlider()',dc = 'attributeGapSlider()')
    mc.floatSliderGrp('scrapeSlider',  v = 0.3, min = 0.01, max = 1,  fmx = 5, s = 0.01, cw3 = [55,40,180] , label = "Scrape   " ,field =True)
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.setParent( '..' )
    ########################################################################################################################################################################
    mc.frameLayout('alignmentFrame', cll= 1, cl= 1, label= "Alignment" , bgc = [0.28,0.2,0.28]  , w= 300)
    mc.text(l ='',h=1)
    mc.rowColumnLayout(nc=8, cw=[(1,40),(2,50),(3,5),(4,50),(5,5),(6,50),(7,10),(8,80)])
    mc.text(l ='Rotate',h=20)
    mc.iconTextButton( style='textOnly', l= "X",rpt = True, c = lambda *_: QChangeCutterDir('X'), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.iconTextButton( style='textOnly', l= "Y",rpt = True, c = lambda *_: QChangeCutterDir('Y'), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.iconTextButton( style='textOnly', l= "Z",rpt = True, c = lambda *_: QChangeCutterDir('Z'), bgc = [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.rowColumnLayout(nc=4, cw=[(1,40),(2,200),(3,5),(4,170),(5,50)])
    mc.text(l ='Border',h=20)
    mc.intSliderGrp('bboxDivSlider',     v = 2,   min = 1 ,    max = 10,  fmx = 20, s = 1, cw3 = [10,40,170] , label = "" ,field =True ,dc= 'borderAlginBBoxDivUpdate()')
    mc.button('borderAlginButton', l= 'On/Off', w = 50, bgc = [0.28,0.28,0.28],c='borderAlginBBoxToggle()')
    mc.setParent( '..' )
    mc.rowColumnLayout(nc=8, cw=[(1,40),(2,50),(3,5),(4,50),(5,5),(6,50),(7,10),(8,80)])
    mc.text(l ='Axis',h=20)
    mc.button('toggleAxisX', l= "X", c = lambda *_: toggleAxisButton('X'), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('toggleAxisY' , l= "Y", c = lambda *_: toggleAxisButton('Y'), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('toggleAxisZ' , l= "Z", c = lambda *_: toggleAxisButton('Z'), bgc = [0.28,0.28,0.28] )
    mc.text(l ='',h=20)
    mc.button('toggleAxisXYZ',  l= "XYZ", c = lambda *_: toggleAxisButton('XYZ'), bgc = [0.3, 0.5, 0.6] )
    mc.setParent( '..' )
    mc.rowColumnLayout(nc=6, cw=[(1,40),(2,80),(3,5),(4,80),(5,5),(6,80)])
    mc.text(l ='Snap')
    mc.iconTextButton(w = 50,style='textOnly' , l= "Border", rpt = True, c = 'alignCutterToBase()', bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.iconTextButton(w = 50,style='textOnly' , l= "Last Cutter", rpt = True, c = 'alignLastCutter()', bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.iconTextButton(w = 50,style='textOnly' , l= "Select Cutter", rpt = True, c = 'alignSelCutter()', bgc = [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.rowColumnLayout(nc=6, cw=[(1,40),(2,80),(3,5),(4,80),(5,5),(6,80)])
    mc.text(l ='Even',h=20)
    mc.iconTextButton(w = 50,style='textOnly' , l= "left / right", rpt = True, c = lambda *_: evenObjLineUp('x'), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.iconTextButton(w = 50,style='textOnly' , l= "up/ down", rpt = True, c = lambda *_: evenObjLineUp('y'), bgc = [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.text(l ='',h=3)
    mc.setParent( '..' )
    ########################################################################################################################################################################
    mc.frameLayout('patternFrame',cll= 1, cl= 1, label= "Pattern" ,  bgc = [0.28,0.2,0.28]  , w= 300)
    mc.text(l ='',h=1)
    mc.rowColumnLayout(nc=8, cw=[(1,40),(2,50),(3,5),(4,50),(5,5),(6,50),(7,10),(8,80)])
    mc.text(l ='Type',h=20)
    mc.button('arrayLinear', l= "Linear",  c = lambda *_: toggleArrayType(), bgc = [0.3, 0.5, 0.6] )
    mc.text(l ='')
    mc.button('arrayRadial' , l= "Radial", c = lambda *_: toggleArrayType(), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.text(l ='')
    mc.text(l ='')
    mc.button( l= "Freeze", c = lambda *_: instBake(), bgc = [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.rowColumnLayout(nc=8, cw=[(1,40),(2,50),(3,5),(4,50),(5,5),(6,50),(7,10),(8,80)])
    mc.text(l ='Axis',h=20)
    mc.button('arrayAxisX', l= "X", c = lambda *_: arrayPattrn('X'), bgc =  [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('arrayAxisY' , l= "Y", c = lambda *_: arrayPattrn('Y'), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button('arrayAxisZ' , l= "Z", c = lambda *_: arrayPattrn('Z'), bgc = [0.28,0.28,0.28] )
    mc.text(l ='')
    mc.button(  l= "Remove", c = lambda *_: removeArrayGrp(), bgc = [0.28,0.28,0.28] )
    mc.setParent( '..' )
    mc.rowColumnLayout()
    mc.columnLayout()
    mc.intSliderGrp('instNumSlider',  v = 1,   min = 1,    max = 10,  fmx = 20 ,s = 1, cw3 = [55,40,180] , label = "Number" ,field =True,cc = lambda *_: instReNew(),dc = lambda *_: instReNew() )
    mc.floatSliderGrp('disSlider', v = 1,   min = -3,    max = 3,  fmx = 20 ,fmn = -20, s = 0.01, cw3 = [55,40,180] , label = "Distance", field =True, cc ='instDistanceUpdate()',dc ='instDistanceUpdate()')
    mc.text(l ='',h=3)
    mc.setParent( '..' )
    mc.setParent( '..' )
    mc.setParent( '..' )
    ##########################################################################################################################################################################
    mc.frameLayout('meshBevelManagerFrame',cll= 1, cl= 1, label= "Mesh Bevel Manager" ,  bgc = [0.28,0.2,0.28] , w= 300)
    mc.text(l ='',h=1)
    mc.rowColumnLayout(nc=4 ,cw=[(1,80),(2, 185),(3,5),(4, 58)])
    mc.text(l ='',h=20)
    mc.iconTextButton('preBevelButton',  w=40,style='textOnly', l= "Bevel Manager", rpt = True, c = 'jwSpeedCutBevelMangerSetup()', bgc = [0.14, 0.14, 0.14] )
    mc.separator( height=15, style='none' )
    mc.setParent( '..' )
    mc.separator( height=15, style='none' )
    mc.commandEcho( state=False )
    mc.scriptEditorInfo(suppressWarnings=0,suppressInfo=0,se=0)
    checkBaseMeshList()
    global cutType 
    cutType = 1
    global cameraUsed
    cameraUsed = []
    global storeOrtho
    storeOrtho = 0
    global sceneSize
    sceneSize = 0.01
    dock = mc.workspaceControl("jwSpeedCutDock", e=1 ,dockToMainWindow=("right", 0))
