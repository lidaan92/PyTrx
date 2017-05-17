# -*- coding: utf-8 -*-
'''
This script is part of PyTrx, an object-oriented programme created for the 
purpose of calculating real-world measurements from oblique images and 
time-lapse image series.

The Camera Environment module of PyTrx. This module contains the 
object-constructors and functions for:
(1) Representing a camera model in three-dimensional space
(2) Effective translation of measurements in an XY image plane to XYZ 
    real-world coordinates
The projection and inverse transformation functions are based on 
those available in the ImGRAFT toolbox for Matlab. Translations from
ImGRAFT are noted in the comments.

Classes:
GCPs:       A class to represent the geography of the camera scene and handle 
            data associated with this (Ground Control Points, the DEM and the 
            image that the GCPs correspond to).
CamCalib:   A class that handles the camera calibration values and provides
            image correction functionality. 
CamEnv:     A class that represents the camera object. This object inherits
            from the GCPs and CamCalib classes, containing information about 
            the intrinsic matrix, lens distortion parameters, camera pose 
            (position and direction), GCPs, and the DEM.
    
@author: Nick Hulton (Nick.Hulton@ed.ac.uk)
         Lynne Addison
         Penny How (p.how@ed.ac.uk)
'''

#Import packages
from FileHandler import readMatrixDistortion, readGCPs
import numpy as np
from DEM import ExplicitRaster,load_DEM,voxelviewshed
from Images import CamImage
from scipy import interpolate
import sys

#------------------------------------------------------------------------------

class GCPs():    
    '''A class representing the geography of the camera scene. Contains
    ground control points, as the world and image points, the DEM data and 
    extent, and the image the ground control points correspond to, as an 
    Image object. 
    
    Inputs:
        - DEMpath: The file path of the ASCII DEM.
        - GCPpath: The file path of the GCP text file, with a header line, and
          tab delimited x, y, z world coordinates and xy image on each line.
        - imagePath: The file path of the image the GCPs correspond to.'''
    
    def __init__(self, dem, GCPpath, imagePath):
        '''Constructor to initiate a geography object.'''                
        #DEM handling
        self._dem = dem
       
        #Get image from CamImage object
        if imagePath!=None:
            self._gcpImage=CamImage(imagePath)
        
        #Get GCP data using the readGCP function in FileHandler
        if GCPpath!=None:
            world, image = readGCPs(GCPpath)
            self._gcpworld = world
            self._gcpimage = image                

        
    def getGCPs(self):
        '''Return the world and image GCPs.'''       
        return self._gcpworld, self._gcpimage

        
    def getDEM(self):
        '''Return the dem object.'''       
        return self._dem

    
    def getImage(self):
        '''Return the GCP reference image.'''
        
        return self._gcpImage

        
#------------------------------------------------------------------------------      

class CamCalib(object):
    '''This base class models a standard camera calibration matrix as per 
    OpenCV, MatLab and ImGRAFT. The class uses a standard pinhole camera model, 
    drawing on the functions within OpenCV. A scene view is formed by 
    projecting 3D points into the image plane using a perspective 
    transformation.     
    
    The camera intrinsic matrix is defined as a 3 x 3 array:        
        fx 0  0
        s  fy 0
        cx cy 1    
    with:
        - fx and fy is the camera focal length (in pixel units) and cx and cy
            as the location of the image centre (in pixels too)
        - s is the skew
        - cx, cy are the image dimensions in pixels
        
    In addition, the radial distortion and tangential distortion are 
    represented as a series of coefficients. These distortions are introduced 
    by discrepancies in the camera lens and between the lens and the camera 
    sensor:
        - Radial Distortion Coefficients: k ([k1,k2,k3,k4,k5,k6]), between 2 
          and 6 coefficients needed
        - Tangential Distortion Coefficients: p ([p1,p2])
    
    The object can be initiated directly either as a list of three elements for 
    each of the intrinsic, tangential and radial arrays, or by refencing a file 
    (.mat or .txt) containing the calibration data in a pre-designated format.'''
    
    def __init__(self,*args): 
        '''Constructor to initiate a calibration object.'''        
        ###Also need to deal with None argument to set calibration values for
        ###Neutral/ nil calibration
    
        failed=False
        
        if len(args)==1:
            
            #Read calibration from file
            if isinstance(args[0],str):
                print('\nAttempting to read camera calibs from a single file')
                args=readMatrixDistortion(args[0])
                args=self.checkMatrix(args)
                if args==None:
                    failed=True
                else:
                    self._intrMat=args[0]
                    self._tanCorr=args[1]
                    self._radCorr=args[2]
                    
            #Read calibration from several files        
            elif isinstance(args[0],list):
                print('\nAttempting to read camera calibs from average over several files')
                intrMat=[]
                tanCorr=[]
                radCorr=[]               
                for item in args[0]:
                    print item
                    if isinstance(item,str):
                        arg=readMatrixDistortion(item)
                        print arg
                        arg=self.checkMatrix(arg)
                        print arg
                        if arg==None:
                            failed=True
                            break
                        else:
                            intrMat.append(arg[0])
                            tanCorr.append(arg[1])
                            radCorr.append(arg[2])
                    else:
                        failed=True
                print intrMat
                print sum(intrMat)
                print len(intrMat)
                self._intrMat = sum(intrMat)/len(intrMat)
                self._tanCorr = sum(tanCorr)/len(tanCorr)
                self._radCorr = sum(radCorr)/len(radCorr)
                
                print '\n\nint_matrix',self._intrMat,'\n'  
                
            else:
                failed=True
        
        #Read calibration from list
        elif len(args)==3:   
            print('Attempting to make camera calibs from raw data sequences')
            args=self.checkMatrix(args)            
            self._intrMat=args[0]
            self._tanCorr=args[1]
            self._radCorr=args[2]
        else:
            failed=True
            
        if failed:
            print 'Error creating camera calibration object:'
            print '\tPlease check calibration specification or files'
            return None
            
        self._focLen=[self._intrMat[0,0], self._intrMat[1,1]]       
        self._camCen=[self._intrMat[2,0], self._intrMat[2,1]] 
        self._intrMatCV2=None
                
            
    def getCalibdata(self):
        '''Return camera matrix, and tangential and radial distortion 
        coefficients.'''
        return self._intrMat,self._tanCorr,self._radCorr

        
    def getCamMatrix(self):
        '''Return camera matrix.'''
        return self._intrMat

    
    def getDistortCoeffsCv2(self):
        '''Return radial and tangential distortion coefficients.'''
        #Returns certain number of values depending on number of coefficients
        #inputted        
        if self._radCorr[3]!=0.0:
            return np.append(self._radCorr[0:2],self._tanCorr,
                             self._radCorr[2:])
        elif self._radCorr[2]!=0.0:
            return np.append(np.append(self._radCorr[0:2],self._tanCorr),
                             self._radCorr[2:3])
        else:
            return np.append(self._radCorrc[0:2],self._tanCorr)

        
    def getCamMatrixCV2(self):
        '''Return camera matrix in a structure that is compatible with 
        subsequent photogrammetric processing using OpenCV.'''
        if self._intrMatCV2==None:
            
            # Transpose if 0's are not in correct places
            if (self._intrMat[2,0]!=0 and self._intrMat[2,1]!=0 and 
                self._intrMat[0,2]==0 and self._intrMat[1,2]==0):
                self._intrMatCV2 = self._intrMat.transpose()
            else:
                self._intrMatCV2=self._intrMat[:]
                
            # Set 0's and 1's in the correct locations
            it=np.array([[0,1],[1,0],[2,0],[2,1]])                 
            for i in range(4):
                x = it[i,0]
                y = it[i,1]
                self._intrMatCV2[x,y]=0.        
            self._intrMatCV2[2,2]=1. 
    
        return self._intrMatCV2

        
    def reportCalibData(self):
        '''Self reporter for Camera Calibration object data.'''
        print '\nData from camera calibration object:'
        print 'Intrinsic Matrix:'
        for row in self._intrMat:
                print row[0],row[1],row[2]
        print 'Tangential Correction:'
        print self._tanCorr[0],self._tanCorr[1]
        print 'Radial Correction:'
        print (self._radCorr[0],self._radCorr[1],self._radCorr[2],
               self._radCorr[3],self._radCorr[4],self._radCorr[5])
        print 'Focal Length:'
        print self._focLen
        print 'Camera Centre:'
        print self._camCen        

        
    def checkMatrix(self,matrix):
        '''Function to support the calibrate function. Checks and converts the 
        intrinsic matrix to the correct format for calibration with opencv.'''  
        ### this is moved over from readfile.  Need to check calibration matrices
        ### howevever obtained...
        if matrix==None:
            return None
        
        #Check matrix
        intrMat=matrix[0]
        
        #Check tangential distortion coefficients
        tanDis=np.zeros(2)
        td = np.array(matrix[1]) 
        tanDis[:td.size] = td
        
        #Check radial distortion coefficients
        radDis=np.zeros(6)
        rd = np.array(matrix[2]) 
        radDis[:rd.size] = rd
        
    
#        #Transpose if 0's are not in correct places
#        if matrix[2,0]!=0 and matrix[2,1]!=0 and matrix[0,2]==0 and matrix[1,2]==0:
#            mat = matrix.transpose()
#        else:
#            mat = matrix
#         
#        # Set 0's and 1's in the correct locations
#        it=np.array([0,1,1,0,2,0,2,1])     
#        it.shape=(4,2)
#        for i in range(4):
#            x = it[i,0]
#            y = it[i,1]
#            mat[x,y]=0        
#        mat[2,2]=1 
    
        return intrMat,tanDis,radDis
        
    #    def __checkMatices__():
    #    radDis=np.zeros(6)
    #    tanDis=np.zeros(2)
    #    rd = np.array(calibDict["RadialDistortion"]) # k1,k2,k3
    #    radDis[:rd.size] = rd
    #    td = np.array(calibDict["TangentialDistortion"]) # p1,p2
    #    tanDis[:td.size] = td


#------------------------------------------------------------------------------        

###NICK'S OLD CODE. MAKE SURE EVERYTHING HAS BEEN MOVED OVER TO THE NEW CAMERA
###CLASS.
#class Camera(CamCalib):
#    '''A class to represent a distorted camera model.
#
# This class is an implementation of a distorted camera model.
# Implements CV2 camera model: <http://docs.opencv.org/modules/calib3d/doc/camera_calibration_and_3d_reconstruction.html>
# and as implented in ImGRAFT: <http://imgraft.glaciology.net > 
# 
#   Camera calibration coefficient values are inherited by the super-class
#
#   self.imgSz   - size of image in pixels [#rows, #columns] #matlab=imgz
#   self.camLoc     - world coordinates of camera [x,y,z] (three element array [0-2]) #matlab=xyz
#   self.viewDir - [yaw,pitch,roll]. Yaw: rotation about z (rotation about vertical axis) #matlab=viewdir
#                              Pitch: look up/down angle (rotation about horizontal axis orthogonal to principal lens direction)
#                              Roll: camera roll - horizon tilt (rotation about horizontal axis along principal lens direction).'''
#
#
#    def __init__(self,imgSz=None,camcalib=None,camLoc=None,viewDir=None,DEMdensify=1.0):
#
## set up the camera calibration by calling the super class.  This should
## be a list either of the intrinsic matrix, tangential and radial correction
## matrices, or a list of where the calibration files are        
#        super(camcalib)
#        
#        self._names={'imgSz':'Image Size','camLoc':'Camera Location','viewDir':'View Direction'}
#        
## for other vairables, allow passed variable to be any tuple or list or array 
## but convert to array form as new object if not null and correct size
## check size passed is as expceted        
# 
## image size (pixels)
#        self.imgSz=self.__setInstVar__(imgSz,2,self._names['imgSz']) 
#               
## camera location (real world co-ordinates)
#        self.camLoc=self.__setInstVar__(camLoc,3,self._names['camLoc'])     
#            
## camera orientation in real world (radians with 0 as North)
#        self.viewDir=self.__setInstVar__(viewDir,3,self._names['viewDir'])  
#
#
#        self.DEMdensify=DEMdensify
#
#        self._setInvProjVars()
#        
#    def __setInstVar__(self,var,specLen,txt): 
#        if (var!=None):
#            if len(var)==specLen:
#                return np.array(var,dtype=np.float32)
#            else:
#                print txt + ' badly speficified - setting to None'
#                return None
#        else:
#            return np.zeros(specLen,dtype=np.float32)


class CamEnv(CamCalib):    
    ''' A class to represent the camera object, containing the intrinsic
    matrix, distortion parameters and camera pose (position and direction).
    
    Also inherits the geography class, representing the ground control point 
    data for the camera: two sets of points and the corresponding image and DEM.
    
    Inputs:
        -name, the reference name for the camera
        -GCPpath, the file path of the GCPs, for the GCPs object
        -DEMpath, the file path for the DEM, for the GCPs object
        -imagePath, the file path for the GCP reference image, for the GCPs object
        -calibPath, the file path for the calibration file. This can be
            either as a .mat Matlab file or a text file. The text file should 
            be of the following tab delimited format:
                RadialDistortion
                [x y z]
                TangentialDistortion
                [x y]
                IntrinsicMatrix
                [x y z]
                [x y z]
                [x y z]
                End
        -coords, the x,y,z coordinates of the camera location, as a list
        -ypr, the yaw, pitch and roll of the camera, as a list '''
    
#    def __init__(self, name, GCPpath, DEMpath, imagePath, calibPath, coords, ypr=[0,0,0]):

    def __init__(self, envFile):
        '''Constructor to initiate Camera Environment object.''' 
        ### Eventually modify this to allow a more flexible
        ### constructor to take a raw input specification in addition to 
        ### file input.
            
        #Read parameters from the environment file             
        params = self.dataFromFile(envFile)

        if params==False:
            print '\nUnable to define camera environment\n'
            print '\nExiting programme\n'
            sys.exit()
        else:
            name, GCPpath, DEMpath, imagePath, calibPath, coords, ypr, DEMdensify = params           
        
        #Set up object parameters
        self._name = name
        self._camloc = np.array(coords)
        self._DEMpath = DEMpath        
        self._DEMdensify=DEMdensify
        self._GCPpath = GCPpath
        self._imagePath = imagePath
        self._refImage=CamImage(imagePath)

        #Set yaw, pitch and roll to 0 if no information is given        
        if ypr == None:
            self._direction = [0,0,0]
        else:
            self._direction = ypr  

        #Initialise CamCalib object for calibration information        
        self._calibPath=calibPath
        CamCalib.__init__(self,calibPath)                
        
        if ypr == None:
            self._camDirection = np.array([0,0,0])
        else:
            self._camDirection =  np.array(ypr)

        #Leave DEM and inverse projection variables empty to begin with
        self._DEM=None
        self._invProjVars=None
            
        ###Load the dem 
        ###Again this a a fudge for now since we're only permitting .Mat files
        #self._DEM=DEM_FromMat(self._DEMpath)
        #print 'DEM Loaded'
        #if self._DEMdensify!=1:
            #self._DEM=self._DEM.densify(self._DEMdensify)
        
        #Initialise GCPs object for GCP and DEM information
        if (self._GCPpath!=None and self._imagePath!=None):
            print '\nCreating GCP environment'
            self._gcp=GCPs(self._DEM, self._GCPpath, self._imagePath)        
        
       
    def dataFromFile(self, filename):
        '''Read CamEnv data from .txt file containing keywords and file paths
        to associated data.'''
        #Define keywords to search for in file        
        self.key_labels={"name":"camera_environment_name",
                         "GCPpath":"gcp_path",
                         "DEMpath":"dem_path",
                         "imagePath":"image_path",
                         "calibPath":"calibration_path",
                         "coords":"camera_location",
                         "ypr":"yaw_pitch_roll",
                         "DEMdensify":"dem_densification"}
        key_lines=dict(self.key_labels)
        for key in key_lines:
            key_lines.update({key:None})
        
        #Extract all lines in the specification file                        
        f=open(filename)
        lines=f.readlines()
        f.close()
 
        #Search for keywords and identify which line they are in       
        for i in range(len(lines)):
            stripped=lines[i].split("#")[0].strip().lower().replace(" ","")
            for key in self.key_labels:
                if self.key_labels[key]==stripped:
                    key_lines.update({key:i})

        #Define CamEnv name if information is present in .txt file
        lineNo=key_lines["name"]
        if lineNo!=None:
            name = self.__getFileDataLine__(lines,lineNo)
        else:
            print "\nName not supplied in: " + filename              
            return False

        #Define GCPpath if information is present in .txt file
        lineNo=key_lines["GCPpath"]
        if lineNo!=None:
            GCPpath = self.__getFileDataLine__(lines,lineNo)
        else:
            print "\nGCPpath not supplied in: " + filename              
            GCPpath=None
            
        #Define DEMpath if information is present in .txt file
        lineNo=key_lines["DEMpath"]
        if lineNo!=None:
            DEMpath = self.__getFileDataLine__(lines,lineNo)
        else:
            print "\nDEMpath not supplied in: " + filename              
            return False
            
        #Define imagePath if information is present in .txt file
        lineNo=key_lines["imagePath"]
        if lineNo!=None:
            imagePath = self.__getFileDataLine__(lines,lineNo)
        else:
            print "\nimagePath not supplied in: " + filename              
            return False 

        #Define DEM densification specifications (DEMdensify)          
        lineNo=key_lines["DEMdensify"]
        print "densify line",lineNo
        if lineNo!=None:
            DEMdensify = self.__getFileDataLine__(lines,lineNo)
            DEMdensify = int(DEMdensify)
        else:
            print "\nDem densification level not supplied in: " + filename  
            print "Setting to 1 (No densification)"
            DEMdensify=1

        #Define calibPath if information is present in .txt file
        lineNo=key_lines["calibPath"]
        if lineNo!=None:
            calibPath = self.__getFileDataLine__(lines,lineNo)
            fields = calibPath.translate(None, '[]').split(',')
            calibPath = []
            for f in fields:
                calibPath.append(f)
            if len(calibPath) == 1:
                calibPath = calibPath[0]                
        else:
            print "\ncalibPath not supplied in: " + filename              
            return False   

        #Define camera location coordinates (coords)
        lineNo=key_lines["coords"]
        if lineNo!=None:
            coords = self.__getFileDataLine__(lines,lineNo)
            fields = coords.translate(None, '[]').split()
            coords = []
            for f in fields:
                coords.append(float(f)) 
        else:
            print "\ncoords not supplied in: " + filename              
            return False 

        #Define yaw, pitch, roll if information is present in .txt file
        lineNo=key_lines["ypr"]
        if lineNo!=None:
            ypr = self.__getFileDataLine__(lines,lineNo)
            fields = ypr.translate(None, '[]').split()
            ypr = []
            for f in fields:
                ypr.append(float(f)) 
        else:
            print "\nypr not supplied in: " + filename              
            return False
           
        print name,GCPpath,DEMpath,imagePath,calibPath,coords,ypr,DEMdensify
        return name,GCPpath,DEMpath,imagePath,calibPath,coords,ypr,DEMdensify

    
    def __getFileDataLine__(self,lines,lineNo):
        '''Return a data line from the Camera Environment Specification file.
        '''
        return lines[lineNo+1].split('#')[0].strip()

        
    def getRefImageSize(self):
        '''Return the dimensions of the reference image.'''
        return self._refImage.getImageSize()


    def getDEM(self):
        '''Return the dem object.'''
        #Prepare DEM from file if DEM parameter is empty
        if self._DEM==None:
            self._DEM=load_DEM(self._DEMpath)
            print 'raw extent', self._DEM.getExtent()            
            print 'DEM Loaded'
            
            #DEM densification
            if self._DEMdensify!=1:
                self._DEM=self._DEM.densify(self._DEMdensify)
                print 'densified extent ', self._DEM.getExtent()
                
        return self._DEM

            
    def _setInvProjVars(self):
        '''Set the inverse projection variables, based on the DEM.'''
        print 'Setting inverse projection coefficients'   
        dem=self.getDEM()
        
        X=dem.getData(0)
        Y=dem.getData(1)
        Z=dem.getData(2)
        
        #Define visible extent of the DEM from the location of the camera
        visible=voxelviewshed(dem,self._camloc)
        self._visible=visible
        Z=Z/visible

        #Snap image plane to DEM extent
        XYZ=np.column_stack([X[visible[:]],Y[visible[:]],Z[visible[:]]])
        uv0,dummy,inframe=self.project(XYZ)
        uv0=np.column_stack([uv0,XYZ])
        uv0=uv0[inframe,:]

        #Assign real-world XYZ coordinates to image pixel coordinates         
        X=uv0[:,2]
        Y=uv0[:,3]
        Z=uv0[:,4]
        uv0=uv0[:,0:2]
        
        #Set inverse projection variables
        self._invProjVars=[X,Y,Z,uv0]


    def project(self,xyz):
        '''Project the xyz world coordinates into the corresponding image 
        coordinates (uv). This is primarily executed using the ImGRAFT 
        projection function found in camera.m:            
        uv,depth,inframe=cam.project(xyz)
        
        Inputs:
               xyz: world coordinates            
        Outputs:
               uv: pixel coordinates in image
               depth: view depth
               inframe: boolean vector containing whether each projected
               3d point is inside the frame.
         
        '''
        ###This was in ImGRAFT/Matlab to transpose the input array if it's 
        ###ordered differently 
        #if size(xyz,2)>3
        #   xyz=xyz';
        #end
        #xyz=bsxfun(@minus,xyz,cam.xyz);
        ###need to check xyz is an array of the correct size
        ###this does element-wise subtraction on the array columns
            
        print 'Doing forward projection of Real World Coordinates'
        
        #Get camera location
        xyz=xyz-self._camloc
        
        #Get camera rotation matrix
        Rprime=np.transpose(self.getR())
        
        #Multiply matrix
        xyz=np.dot(xyz,Rprime)
        
        #ImGRAFT/Matlab equiv to below command: 
        #xy=bsxfun(@rdivide,xyz(:,1:2),xyz(:,3))
        xy=xyz[:,0:2]/xyz[:,2:3]
                    
        if False:
            
            #if (not np.allclose(self.radDstrt,[0.,0.,0.,0.,0.,0.])) or 
            #(not np.allclose(self.tanDstrt,[0.,0.])):
            r2=np.sum(xy*xy,1)

            #Have no idea why this line exists - need to ask Aslak                
            r2[r2>4]=4

            #Have to be careful in the translation from Matlab here in terms of 
            #getting the logic right. 
            #Here, 'if not np.allclose(self.radDstrt[2:6], [0., 0., 0., 0.])' 
            #gives the equivalent of 'any(cam.k(3:6)~=0)'
            if not np.allclose(self.radDstrt[2:6], [0., 0., 0., 0.]):
                a=(1. + self.radDstrt[0] * r2+self.radDstrt[1] * r2 * r2 +
                   self.radDstrt[2] * r2 * r2 * r2)
                a=a/(1. + self.radDstrt[3] * r2 + self.radDstrt[4] * r2 * r2 + 
                  self.radDstrt[5]*r2*r2*r2)
            else:
                a=(1. + self.radDstrt[0] * r2 + self.radDstrt[1] * r2 * r2 + 
                   self.radDstrt[2] * r2 * r2 * r2)

            xty=xy[:,0] * xy[:,1]
            
            pt1=a*xy[:,0]+2*self.tanDstrt[0]*xty+self.tanDstrt[1]*(r2+2*xy[:,0]
                                                                   *xy[:,0])
            pt2=a*xy[:,1]+2*self.tanDstrt[0]*xty+self.tanDstrt[1]*(r2+2*xy[:,1]
                                                                   *xy[:,1])
            
            #pt1=xy[:,0]
            #pt2=xy[:,1]
            
            xy=np.column_stack((pt1,pt2))

        #ImGRAFT/Matlab version of code below: 
        #uv=[cam.f[1]*xy(:,1)+cam.c(1), cam.f(2)*xy(:,2)+cam.c(2)];
        uv=np.empty([xy.shape[0],xy.shape[1]])
                   
        for i in range(xy.shape[0]):
            uv[i,0]=self._focLen[0] * xy[i,0] + self._camCen[0]
            uv[i,1]=self._focLen[1] * xy[i,1] + self._camCen[1]
 
        for i in range(xy.shape[0]):
            if xyz[i,2]<=0:
                uv[i,0]=np.nan
                uv[i,1]=np.nan

        depth=xyz[:,2]
        
        #Create empty array representing the image
        inframe=np.zeros(xy.shape[0],dtype=bool)

        #Get size of reference image
        ims=self._refImage.getImageSize()
        
        for i in range(xy.shape[0]):
            inframe[i]=(depth[i]>0)&(uv[i,0]>=1)&(uv[i,1]>=1)
            inframe[i]=inframe[i]&(uv[i,0]<=ims[1])&(uv[i,1]<=ims[0])
        
        return uv,depth,inframe

 
    def invproject(self,uv,quiet=1):  
        '''Inverse project image coordinates (uv) to xyz world coordinates
        using inverse projection variables (set using self._setInvProjVars).         

        uv,depth,inframe=cam.project(xyz)
        
        Inputs:
               uv: pixel coordinates in image           
        Outputs:
               xyz: world coordinates. 
        '''
        if quiet>0:
            print 'Undertaking inverse projection'
        
        #Set inverse projection variables if none exists
        if self._invProjVars==None:
            self._setInvProjVars()            
        
        #Create empty numpy array
        xyz=np.zeros([uv.shape[0],3])
        xyz[::]=float('NaN')
        
        #Get XYZ real world coordinates and corresponding uv coordinates
        X=self._invProjVars[0]
        Y=self._invProjVars[1]
        Z=self._invProjVars[2]
        uv0=self._invProjVars[3]

        #Snap uv and xyz grids together
        xi=interpolate.griddata(uv0, X, uv, method='linear')
        yi=interpolate.griddata(uv0, Y, uv, method='linear')
        zi=interpolate.griddata(uv0, Z, uv, method='linear')
        
        #Return xyz grids                
        xyz=np.column_stack([xi,yi,zi])
        return xyz


    def getR(self):
        '''Calculates Camera rotation matrix calculated from view 
        direction'''

        C = np.cos(self._camDirection) 
        S = np.sin(self._camDirection)
                    
        p=[S[2]*S[1]*C[0]-C[2]*S[0] , S[2]*S[1]*S[0] + C[2]*C[0] , S[2]*C[1]]
        q=[ C[2]*S[1]*C[0] + S[2]*S[0], C[2]*S[1]*S[0] - S[2]*C[0],C[2]*C[1]]
        r=[ C[1]*C[0] , C[1]*S[0] , -S[1]]
            
        value = np.array([p,q,r])
        value[0:2,:]=-value[0:2,:]

        return value

    def report(self):
        '''Reporter for testing that the relevant data has been successfully 
        imported. Testing for:
        - Camera Environment name
        - Camera location (xyz)
        - Reference image
        - DEM
        - DEM densification
        - GCPs
        - Yaw, pitch, roll
        - Camera matrix and distortion coefficients'''
        
        #Camera name and location
        print '\nCamera Environment setup/data:\n'
        print 'Camera Environment name: ',self._name 
        print 'Camera Location [X,Y,Z]:  ',self._camloc
        
        #Reference image
        print 'Reference image used for baseline homography and/or GCP control: ', self._imagePath
        
        #DEM and densification        
        print 'DEM file used for projection:',self._DEMpath
        if self._DEMdensify==1:
            print 'DEM is used at raw resolution'
        else:
            print 'DEM is resampled at '+str(self._DEMdensify)+' times resolution'
        
        #GCPs        
        if self._GCPpath!=None:
            print 'GCP file used to define camera pose: ',self._GCPpath
        else:
            print 'No GCP file defined'
         
        #Yaw, pitch, roll
        if self._direction==[0,0,0]:
            print 'Camera pose assumed unset (zero values)'
        else:
            print 'Camera Pose set as [Roll,Pitch,Yaw]: ',self._direction

        #Camera calibration (matrix and distortion coefficients)
        if isinstance(self._calibPath,list):
            print 'Multiple camera calibration files defined:'
            print self._calibPath
        else:
            print 'Camera calibration file:'
        
        #Report raster DEM details from the DEM class
        if isinstance(self._DEM,ExplicitRaster):
            print '\nDEM set:\n'
            self._DEM.reportDEM()

        #Report calibration parameters from CamCalib class
        self.reportCalibData()


#Tester code to run if main. Requires PyTrx_Tests.py module in visible path
if __name__ == "__main__":
    from PyTrx_Tests import doCalibrationTests,doCamEnvTests
    
    doCalibrationTests()
    doCamEnvTests()
        

