'''
PYTRX CAMERA ENVIRONMENT MODULE

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
ImGRAFT are noted in related script comments.

Classes
GCPs:                       A class to represent the geography of the camera 
                            scene and handle data associated with this (Ground 
                            Control Points, the DEM and the image that the GCPs 
                            correspond to)
CamCalib:                   A class that handles the camera calibration values 
                            and provides image correction functionality 
CamEnv:                     A class that represents the camera object. This 
                            object inherits from the GCPs and CamCalib classes, 
                            containing information about the intrinsic matrix, 
                            lens distortion parameters, camera pose (position 
                            and direction), GCPs, and the DEM

Key stand-alone functions
calibrateImages:            Calibrate a camera from a set of input calibration
                            images. Calibration is performed using a chessboard 
                            calibration approach         
project:                    Project xyz world coordinates into corresponding 
                            image coordinates (uv)
setInvProjVars:             Set the inverse projection variables, based on the 
                            DEM
invproject:                 Inverse project image coordinates (uv) to xyz world 
                            coordinates using inverse projection variables         

@author: Penny How (p.how@ed.ac.uk)
         Nick Hulton 
         Lynne Buie       
'''

#Import PyTrx packages
from FileHandler import readImg, readMatrixDistortion, readGCPs
from Utilities import plotGCPs, plotPrincipalPoint, plotCalib
from DEM import ExplicitRaster,load_DEM,voxelviewshed
from Images import CamImage

#Import other packages
from scipy import interpolate
from PIL import Image
import numpy as np
import cv2
import glob

#------------------------------------------------------------------------------

class GCPs():    
    '''A class representing the geography of the camera scene. Contains
    ground control points, as the world and image points, the DEM data and 
    extent, and the image the ground control points correspond to, as an 
    Image object. 
    
    Args
    DEMpath:        The file path of the ASCII DEM.
    GCPpath:        The file path of the GCP text file, with a header line, and
                    tab delimited x, y, z world coordinates and xy image on 
                    each line.
    imagePath:      The file path of the image the GCPs correspond to.
    '''
    
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
            self._gcpxyz = world
            self._gcpuv = image                

        
    def getGCPs(self):
        '''Return the world and image GCPs.'''       
        return self._gcpxyz, self._gcpuv

        
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
    each of the intrinsic, tangential and radial arrays, or by referencing a 
    file (.mat or .txt) containing the calibration data in a pre-designated 
    format.
    
    Args
    *args:                  Either a calibration text file, a series of 
                            calibration text files, a list of raw parameters, 
                            or a set of calibration images (along with 
                            calibration chessboard dimensions) 
    '''
    
    def __init__(self, *args): 
        '''Constructor to initiate a calibration object.'''            
        failed=False 
            
        #Read calibration from file
        if isinstance(args[0],str):
            print '\nAttempting to read camera calibs from a single file'
            args=readMatrixDistortion(args[0])
            args=self.checkMatrix(args)
            if args==None:
                failed=True
            else:
                self._intrMat=args[0]
                self._tanCorr=args[1]
                self._radCorr=args[2]
                self._calibErr=None
            

        #Read calibration from several files                      
        elif isinstance(args[0],list):                 
            if args[0][0][-4:] == '.txt':
                print('\nAttempting to read camera calibs from average over ' 
                      'several files')
                intrMat=[]
                tanCorr=[]
                radCorr=[]               
                for item in args[0]:
                    if isinstance(item,str):
                        arg=readMatrixDistortion(item)
                        arg=self.checkMatrix(arg)
                        if arg==None:
                            failed=True
                            break
                        else:
                            intrMat.append(arg[0])
                            tanCorr.append(arg[1])
                            radCorr.append(arg[2])
                    else:
                        failed=True

                self._intrMat = sum(intrMat)/len(intrMat)
                self._tanCorr = sum(tanCorr)/len(tanCorr)
                self._radCorr = sum(radCorr)/len(radCorr)
                self._calibErr=None
                
            #Calculate calibration from images                    
            elif args[0][0][-4:] == '.JPG' or '.PNG':
                print ('\nAttempting to calculate camera calibs from input'
                        + ' images')
                calibimgs=[]
                for i in sorted(glob.glob(args[0][0])):
                    calibimgs.append(i)
                    
                arg, err = calibrateImages(calibimgs,[int(args[0][1]),
                                           int(args[0][2])])
                arg = self.checkMatrix(arg)
                
                if arg==None:
                    failed=True
                else:
                    self._intrMat=arg[0]
                    self._tanCorr=arg[1]
                    self._radCorr=arg[2]
                    self._calibErr=err
            else:
                failed=True
        
        #Define calibration from raw input
        elif isinstance(args[0],tuple):
            print ('\nAttempting to make camera calibs from raw data '
                   + 'sequences')
            
            arg = self.checkMatrix([args[0][0],args[0][1],args[0][2]]) 
            
            self._intrMat=arg[0]
            self._tanCorr=arg[1]
            self._radCorr=arg[2]
            self._calibErr=None 
            
        else:
            failed=True
                        
            
        if failed:
            print '\nError creating camera calibration object:'
            print 'Please check calibration specification or files'
            return None
            
        self._focLen=[self._intrMat[0,0], self._intrMat[1,1]]       
        self._camCen=[self._intrMat[2,0], self._intrMat[2,1]] 
        self._intrMatCV2=None
                
            
    def getCalibdata(self):
        '''Return camera matrix, and tangential and radial distortion 
        coefficients.'''
        return self._intrMat, self._tanCorr, self._radCorr

        
    def getCamMatrix(self):
        '''Return camera matrix.'''
        return self._intrMat

    
    def getDistortCoeffsCV2(self):
        '''Return radial and tangential distortion coefficients.'''
        #Returns certain number of values depending on number of coefficients
        #inputted         
        if self._radCorr[3]!=0.0:
            return np.append(np.append(self._radCorr[0:2],self._tanCorr),
                             self._radCorr[2:])
        elif self._radCorr[2]!=0.0:
            return np.append(np.append(self._radCorr[0:2],self._tanCorr),
                             self._radCorr[2:3])
        else:
            return np.append(self._radCorr[0:2],self._tanCorr)

        
    def getCamMatrixCV2(self):
        '''Return camera matrix in a structure that is compatible with 
        subsequent photogrammetric processing using OpenCV.'''
        if self._intrMatCV2 is None:
            
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
        print '\nDATA FROM CAMERA CALIBRATION OBJECT'
        print 'Intrinsic Matrix:'
        for row in self._intrMat:
                print row[0],row[1],row[2]
        print '\nTangential Correction:'
        print self._tanCorr[0],self._tanCorr[1]
        print '\nRadial Correction:'
        print (self._radCorr[0],self._radCorr[1],self._radCorr[2],
               self._radCorr[3],self._radCorr[4],self._radCorr[5])
        print '\nFocal Length:'
        print self._focLen
        print '\nCamera Centre:'
        print self._camCen
        if self._calibErr != None:
            print '\nCalibration Error:'
            print self._calibErr


    def checkMatrix(self, matrix):
        '''Function to support the calibrate function. Checks and converts the 
        intrinsic matrix to the correct format for calibration with opencv.'''  
        ###This is moved over from readfile. Need to check calibration matrices
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
           
        return intrMat, tanDis, radDis

                          
#------------------------------------------------------------------------------
                          
class CamEnv(CamCalib):    
    ''' A class to represent the camera object, containing the intrinsic
    matrix, distortion parameters and camera pose (position and direction).
    
    Also inherits the geography class, representing the ground control point 
    data for the camera: two sets of points and the corresponding image and 
    DEM.
    
    Args
    name:           The reference name for the camera.
    GCPpath:        The file path of the GCPs, for the GCPs object.
    DEMpath:        The file path for the DEM, for the GCPs object.
    imagePath:      The file path for the GCP reference image, for the GCPs 
                    object.
    calibPath:      The file path for the calibration file. This can be
                    either as a .mat Matlab file or a text file. The text file 
                    should be of the following tab delimited format:
                    RadialDistortion
                    [k1 k2 k3...k7]
                    TangentialDistortion
                    [p1 p2]
                    IntrinsicMatrix
                    [x y z]
                    [x y z]
                    [x y z]
                    End
    coords:         The x,y,z coordinates of the camera location, as a list.
    ypr:            The yaw, pitch and roll of the camera, as a list.
    '''
    
    def __init__(self, envFile):
        '''Constructor to initiate Camera Environment object.''' 
        print '\nINITIALISING CAMERA ENVIRONMENT'
 
        #Read camera environment from text file        
        if isinstance(envFile, str):
            #Read parameters from the environment file 
            params = self.dataFromFile(envFile)
    
            #Exit programme if file is invalid
            if params==False:
                print '\nUnable to define camera environment'
                pass
            
            #Extract input files from camera environment file 
            else:
                (name, GCPpath, DEMpath, imagePath, 
                 calibPath, coords, ypr, DEMdensify) = params           

        #Read camera environment from files as input variables
        elif isinstance(envFile, list):
            name = envFile[0]
            GCPpath = envFile[1]
            DEMpath = envFile[2]
            imagePath = envFile[3]
            calibPath = envFile[4]
            coords = envFile[5]
            ypr = envFile[6]
            DEMdensify = envFile[7]

        else:
            print '\nInvalid camera environment data type'
            pass
            
        #Set up object parameters
        self._name = name
        self._camloc = np.array(coords)
        self._DEMpath = DEMpath        
        self._DEMdensify = DEMdensify
        self._GCPpath = GCPpath
        self._imagePath = imagePath
        self._refImage = CamImage(imagePath)      

        #Set yaw, pitch and roll to 0 if no information is given        
        if ypr is None:
            self._camDirection = np.array([0,0,0])
        else:
            self._camDirection =  np.array(ypr)

        #Initialise CamCalib object for calibration information        
        self._calibPath=calibPath
        CamCalib.__init__(self,calibPath)                
                
        #Leave DEM and inverse projection variables empty to begin with
        self._DEM = None
        self._invProjVars = None
      
        #Initialise GCPs object for GCP and DEM information
        if (self._GCPpath!=None and self._imagePath!=None):
            print '\nCreating GCP environment'
            self._gcp=GCPs(self._DEM, self._GCPpath, self._imagePath)        
        
       
    def dataFromFile(self, filename):
        '''Read CamEnv data from .txt file containing keywords and file paths
        to associated data.
        '''
        #Define keywords to search for in file        
        self.key_labels={'name':'camera_environment_name',
                         'GCPpath':'gcp_path',
                         'DEMpath':'dem_path',
                         'imagePath':'image_path',
                         'calibPath':'calibration_path',
                         'coords':'camera_location',
                         'ypr':'yaw_pitch_roll',
                         'DEMdensify':'dem_densification'}
        key_lines=dict(self.key_labels)
        for key in key_lines:
            key_lines.update({key:None})
        
        #Extract all lines in the specification file                       
#        f=filename.open() 
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
            print "\nCoordinates not supplied in: " + filename              
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
            print "\nYPR not supplied in: " + filename              
            return False
           
        return name,GCPpath,DEMpath,imagePath,calibPath,coords,ypr,DEMdensify

    
    def __getFileDataLine__(self,lines,lineNo):
        '''Return a data line from the Camera Environment Specification file.'''
        return lines[lineNo+1].split('#')[0].strip()

        
    def getRefImageSize(self):
        '''Return the dimensions of the reference image.'''
        return self._refImage.getImageSize()


    def getDEM(self):
        '''Return DEM as ExplicitRaster type.'''
        if self._DEM is None:
            dem = load_DEM(self._DEMpath)
            if self._DEMdensify>1:
                dem=dem.densify(self._DEMdensify)
            self._DEM=dem
            return self._DEM
        
        else:
            return self._DEM


    def showGCPs(self):
        '''Plot GCPs in image plane and DEM scene.'''
        xyz, uv = self._gcp.getGCPs()               #Get GCP positions
        dem = self.getDEM()                         #Get DEM        
        refimage=self._refImage
        img = refimage.getImageArray()              #Get image array
        imn = refimage.getImageName()               #Get image name

        #Plot GCPs
        plotGCPs([xyz,uv], img, imn, dem, self._camloc, extent=None)            


    def showPrincipalPoint(self):
        '''Plot Principal Point on reference image.'''
        refimage=self._refImage
        img = refimage.getImageArray()              #Get image array
        imn = refimage.getImageName()               #Get image name
        
        #Plot principal point 
        plotPrincipalPoint(self._camCen, img, imn)


    def showCalib(self):
        '''Plot corrected and uncorrected reference image.'''
        refimage=self._refImage
        img = refimage.getImageArray()              #Get image array
        imn = refimage.getImageName()               #Get image name        
        matrix = self.getCamMatrixCV2()             #Get camera matrix
        distort = self.getDistortCoeffsCV2()        #Get distortion parameters

        #Plot calibrated image
        plotCalib(matrix, distort, img, imn)       


    def reportCamData(self):
        '''Reporter for testing that the relevant data has been successfully 
        imported. Testing for:
        - Camera Environment name
        - Camera location (xyz)
        - Reference image
        - DEM
        - DEM densification
        - GCPs
        - Yaw, pitch, roll
        - Camera matrix and distortion coefficients
        '''
        
        #Camera name and location
        print '\nCAMERA ENVIRONMENT REPORT'
        print 'Camera Environment name: ',self._name 
        print 'Camera Location [X,Y,Z]:  ',self._camloc
        
        #Reference image
        print ('\nReference image used for baseline homography and/or GCP' 
               'control: ')
        print self._imagePath
        
        #DEM and densification        
        print '\nDEM file used for projection:',
        print self._DEMpath
        if self._DEMdensify==1:
            print 'DEM is used at raw resolution'
        else:
            print ('DEM is resampled at '+str(self._DEMdensify) + 
                  ' times resolution')
        
        #GCPs        
        if self._GCPpath!=None:
            print '\nGCP file used to define camera pose:'
            print self._GCPpath
        else:
            print 'No GCP file defined'
         
        #Yaw, pitch, roll
        if self._camDirection is None:
            print '\nCamera pose assumed unset (zero values)'
        else:
            print '\nCamera pose set as [Roll,Pitch,Yaw]: '
            print self._camDirection

        #Camera calibration (matrix and distortion coefficients)
        if isinstance(self._calibPath[0],list):
            if self._calibPath[0][0][-4:] == '.txt':
                print '\nCalibration calculated from multiple files:'
                print self._calibPath

        elif isinstance(self._calibPath[0],str):
            if self._calibPath[0][-4:] == '.txt':
                print '\nCalibration calculated from single file:'
                print self._calibPath
                
            elif self._calibPath[0][0][-4:] == '.JPG' or '.PNG':
                print '\nCalibration calculated from raw images:'                      
                print self._calibPath
                                         
        elif isinstance(self._calibPath[0],np.array):   
            print '\nCalibration calculated from raw data:' 
            print self._calibPath
        
        else:
            print '\nCalibration undefined'
        
        
        #Report raster DEM details from the DEM class
        if isinstance(self._DEM,ExplicitRaster):
            print '\nDEM set:'
            self._DEM.reportDEM()

        #Report calibration parameters from CamCalib class
        self.reportCalibData()


def calibrateImages(imageFiles, xy):
    '''Function for calibrating a camera from a set of input calibration
    images. Calibration is performed using OpenCV's chessboard calibration 
    functions. Input images (imageFile) need to be of a chessboard with 
    regular dimensions and a known number of corner features (xy).
    
    Please note that OpenCV's calibrateCamera function is incompatible 
    between different versions of OpenCV. Included here are both functions 
    for version 2 and version 3. Please see OpenCV's documentation for 
    newer versions.
    '''        
    #Define shape of array
    objp = np.zeros((xy[0]*xy[1],3), np.float32)           
    objp[:,:2] = np.mgrid[0:xy[1],0:xy[0]].T.reshape(-1,2) 

    #Array to store object pts and img pts from all images
    objpoints = []                                   
    imgpoints = []                                   
    
    #Set image counter for loop
    imageCount = 0
    
    #Loop to determine if each image contains a chessboard pattern and 
    #store corner values if it does
    for fname in imageFiles:
        
        #Read file as an image using OpenCV
        img = cv2.imread(fname)   

        #Change RGB values to grayscale             
        gray = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)    
        
        #Find chessboard corners in image
        patternFound, corners = cv2.findChessboardCorners(gray,
                                                          (xy[1],xy[0]),
                                                          None)
        
        #Cycle through images, print if chessboard corners have been found 
        #for each image
        imageCount += 1
        print str(imageCount) + ': ' + str(patternFound) + ' ' + fname
        
        #If found, append object points to objp array
        if patternFound == True:
            objpoints.append(objp)
            
            #Determine chessboard corners to subpixel accuracy
            #Inputs: winSize specified 11x11, zeroZone is nothing (-1,-1), 
            #opencv criteria
            cv2.cornerSubPix(gray,corners,(11,11),(-1,-1),
                             (cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER,
                             30,0.001))
                             
            imgpoints.append(corners)
            
            #Draw and display corners
            cv2.drawChessboardCorners(img,(xy[1],xy[0]),corners,
                                      patternFound)
    
    #Try OpenCV v3 calibration function
    try:
        #Calculate initial camera matrix and distortion
        err,mtx,dist,rvecs,tvecs = cv2.calibrateCamera(objpoints,
                                                       imgpoints,
                                                       gray.shape[::-1],
                                                       None,
                                                       5)
        #Retain principal point coordinates
        pp = [mtx[0][2],mtx[1][2]]
        
        #Optimise camera matrix and distortion using fixed principal point
        err,mtx,dist,rvecs,tvecs = cv2.calibrateCamera(objpoints,
                                                       imgpoints,
                                                       gray.shape[::-1],
                                                       mtx,
                                                       5,
                                                       flags=cv2.CALIB_FIX_PRINCIPAL_POINT)

    #Else use OpenCV v2 calibration function
    except:
        #Calculate initial camera matrix and distortion
        err,mtx,dist,rvecs,tvecs = cv2.calibrateCamera(objpoints,
                                                       imgpoints,
                                                       gray.shape[::-1])

        #Retain principal point coordinates
        pp = [mtx[0][2],mtx[1][2]]
        
        #Optimise camera matrix and distortion using fixed principal point
        err,mtx,dist,rvecs,tvecs = cv2.calibrateCamera(objpoints,
                                                       imgpoints,
                                                       gray.shape[::-1],
                                                       cameraMatrix=mtx,
                                                       flags=cv2.CALIB_FIX_PRINCIPAL_POINT)                                                                     

    #Change matrix structure for compatibility with PyTrx
    mtx = np.array([mtx[0][0],mtx[0][1],0,
                   0,mtx[1][1],0,
                   pp[0],pp[1],1]).reshape(3,3)

    
    #Restructure distortion parameters for compatibility with PyTrx
    rad = np.array([dist[0],dist[1],dist[4], 0.0, 0.0, 0.0]).reshape(6)
    tan = np.array(dist[2:4]).reshape(2)
    
    #Return matrix, radial distortion and tangential distortion parameters
    return [mtx, tan, rad], err
        

def constructDEM(dempath, densefactor):
    '''Return the dem object.'''
    #Prepare DEM from file
    dem=load_DEM(dempath)
        
    #DEM densification
    if densefactor>1:
        dem=dem.densify(densefactor)
            
    return dem

            
def setInvProjVars(dem, camloc, camdir, radial, tangen, foclen, camcen, refimg):
    '''Set the inverse projection variables, based on the DEM.'''             
    print '\nSetting inverse projection coefficients'         

    if isinstance(dem, list):
        dem=constructDEM(dem[0], dem[1])
        X=dem.getData(0)
        Y=dem.getData(1)
        Z=dem.getData(2)        
    else:    
        X=dem.getData(0)
        Y=dem.getData(1)
        Z=dem.getData(2)
    
    #Define visible extent of the DEM from the location of the camera
    visible=voxelviewshed(dem, camloc)
#    self._visible=visible
#        Z=Z/visible


    #Snap image plane to DEM extent
    XYZ=np.column_stack([X[visible[:]],Y[visible[:]],Z[visible[:]]])
    uv0,dummy,inframe=project(camloc, camdir, radial, tangen, foclen, 
                              camcen, refimg, XYZ)
    uv0=np.column_stack([uv0,XYZ])
    uv0=uv0[inframe,:]

    #Assign real-world XYZ coordinates to image pixel coordinates         
    X=uv0[:,2]
    Y=uv0[:,3]
    Z=uv0[:,4]
    uv0=uv0[:,0:2]
    
    #Set inverse projection variables
    print '\nInverse projection coefficients defined'
    invProjVars=[X,Y,Z,uv0]              
    return invProjVars
            

def project(camloc, camdirection, radial, tangen, foclen, camcen, refimg, xyz):
    '''Project the xyz world coordinates into the corresponding image 
    coordinates (uv). This is primarily executed using the ImGRAFT 
    projection function found in camera.m:            
    uv,depth,inframe=cam.project(xyz)
    
    Inputs
    xyz:                World coordinates.            
    
    Outputs
    uv:                 Pixel coordinates in image.
    depth:              View depth.
    inframe:            Boolean vector containing whether each projected
                        3d point is inside the frame.        
    '''
    
    #This was in ImGRAFT/Matlab to transpose the input array if it's 
    #ordered differently 
    #if size(xyz,2)>3                                                 (MAT)
    #   xyz=xyz';                                                     (MAT)
    #end                                                              (MAT)
    #xyz=bsxfun(@minus,xyz,cam.xyz);                                  (MAT)
    ###need to check xyz is an array of the correct size
    ###this does element-wise subtraction on the array columns
    
    #Get camera location
    xyz=xyz-camloc
    
    #Get camera rotation matrix
    Rprime=np.transpose(getR(camdirection))
    
    #Multiply matrix
    xyz=np.dot(xyz,Rprime)
    
    #ImGRAFT/Matlab equiv to below command: 
    #xy=bsxfun(@rdivide,xyz(:,1:2),xyz(:,3))                          (MAT)
    xy=xyz[:,0:2]/xyz[:,2:3]
                
    if False:
        #Transposed from ImGRAFT. Have no idea why this line exists 
        #Need to ask Aslak
        r2=np.sum(xy*xy,1)                
        r2[r2>4]=4
        
        #Transposed from ImGRAFT
        if not np.allclose(radial[2:6], [0., 0., 0., 0.]):
            a=(1.+radial[0]*r2+radial[1]*r2*r2+radial[2]*r2*r2*r2)
            a=a/(1.+radial[3]*r2+radial[4]*r2*r2+radial[5]*r2*r2*r2)
        else:
            a=(1.+radial[0]*r2+radial[1]*r2*r2+radial[2]*r2*r2*r2)

        xty=xy[:,0]*xy[:,1]            
        pt1=a*xy[:,0]+2*tangen[0]*xty+tangen[1]*(r2+2*xy[:,0]*xy[:,0])
        pt2=a*xy[:,1]+2*tangen[0]*xty+tangen[1]*(r2+2*xy[:,1]*xy[:,1])            
        xy=np.column_stack((pt1,pt2))

    #ImGRAFT/Matlab version of code below: 
    #uv=[cam.f[1]*xy(:,1)+cam.c(1), cam.f(2)*xy(:,2)+cam.c(2)];       (MAT)
    uv=np.empty([xy.shape[0],xy.shape[1]])
               
    for i in range(xy.shape[0]):
        uv[i,0]=foclen[0] * xy[i,0] + camcen[0]
        uv[i,1]=foclen[1] * xy[i,1] + camcen[1]
 
    for i in range(xy.shape[0]):
        if xyz[i,2]<=0:
            uv[i,0]=np.nan
            uv[i,1]=np.nan

    depth=xyz[:,2]
    
    #Create empty array representing the image
    inframe=np.zeros(xy.shape[0],dtype=bool)

    #Get size of reference image
    if isinstance(refimg, str):
        ims=readImg(refimg)
        ims=ims.shape
    elif isinstance(refimg, np.ndarray):
        ims=refimg.shape
    else:
        ims=refimg.getImageSize()
    
    for i in range(xy.shape[0]):
        inframe[i]=(depth[i]>0)&(uv[i,0]>=1)&(uv[i,1]>=1)
        inframe[i]=inframe[i]&(uv[i,0]<=ims[1])&(uv[i,1]<=ims[0])
    
    return uv,depth,inframe

 
def invproject(uv, invprojvars):  
    '''Inverse project image coordinates (uv) to xyz world coordinates
    using inverse projection variables (set using self._setInvProjVars).         
    This is primarily executed using the ImGRAFT projection function 
    found in camera.m:            
    uv,depth,inframe=cam.project(xyz)
    
    Inputs
    uv:                 Pixel coordinates in image
    invprojvars:        Inverse projection variables
      
    Outputs
    xyz:                World coordinates 
    '''                  
    #Create empty numpy array
    xyz=np.zeros([uv.shape[0],3])
    xyz[::]=float('NaN')
    
    #Get XYZ real world coordinates and corresponding uv coordinates
    X=invprojvars[0]
    Y=invprojvars[1]
    Z=invprojvars[2]
    uv0=invprojvars[3]
    
    #Snap uv and xyz grids together
    xi=interpolate.griddata(uv0, X, uv, method='linear')
    yi=interpolate.griddata(uv0, Y, uv, method='linear')
    zi=interpolate.griddata(uv0, Z, uv, method='linear')
    
    #Return xyz grids                
    xyz=np.column_stack([xi,yi,zi])       
    return xyz


def getR(camDirection):
    '''Calculates camera rotation matrix calculated from view 
    direction.'''

    C = np.cos(camDirection) 
    S = np.sin(camDirection)
                
    p=[S[2]*S[1]*C[0]-C[2]*S[0] , S[2]*S[1]*S[0] + C[2]*C[0] , S[2]*C[1]]
    q=[ C[2]*S[1]*C[0] + S[2]*S[0], C[2]*S[1]*S[0] - S[2]*C[0],C[2]*C[1]]
    r=[ C[1]*C[0] , C[1]*S[0] , -S[1]]
        
    value = np.array([p,q,r])
    value[0:2,:]=-value[0:2,:]

    return value
     
        
#------------------------------------------------------------------------------

#if __name__ == "__main__":   
#    print '\nProgram finished'

#------------------------------------------------------------------------------   