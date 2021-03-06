'''
PYTRX Area MODULE

This script is part of PyTrx, an object-oriented programme created for the 
purpose of calculating real-world measurements from oblique images and 
time-lapse image series.

This is the Area module of PyTrx. It handles the functionality for obtaining 
areal measurements from oblique time-lapse imagery. Specifically, this module 
contains functions for:
(1) Performing automated and manual detection of areal extents in oblique 
    imagery.
(2) Determining real-world surface areas from oblique imagery.

Classes
Area:                           A class for processing change in area (i.e. a 
                                lake or plume) through an image sequence, with 
                                methods for automated and manual detection

Key class functions
calcAutoAreas:                  Automatically detect areas of 
                                interest from a sequence of images and return 
                                uv and xyz measurements
calcManualAreas:                Manually define areas of interest from a 
                                sequence of images and return uv and xyz 
                                measurements
verifyAreas:                    Method to manuall verify all detected polygons 
                                in an image sequence.
                               
Key stand-alone functions
calcAutoArea:                   Automatically detect areas of interest from an
                                image pair and return uv and xyz measurements
calcManualArea:                 Manually define areas of interest from an
                                image pair and return uv and xyz measurements       
                                                                                                                          
@author: Penny How (p.how@ed.ac.uk)
         Nick Hulton 
         Lynne Buie
'''

#Import packages
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import cv2
from PIL import Image
import ogr

#Import PyTrx functions and classes
from FileHandler import readMask
from Images import ImageSequence, enhanceImage
from Velocity import Velocity
from CamEnv import invproject, setInvProjVars


#------------------------------------------------------------------------------
class Area(Velocity):
    '''A class for processing change in area (i.e. a lake or plume) through an 
    image sequence, with methods to calculate extent change in an image plane 
    (px) and real areal change via georectification.
    
    Args:
    imageList (str, list):     List of images, for the ImageSet object.        
    cameraenv (str):           Camera environment parameters which can be read 
                               into the CamEnv class as a text file (see CamEnv 
                               documentation for exact information needed).
    calibFlag (bool):          An indicator of whether images are calibrated, 
                               for the ImageSet object.     
    maxMaskPath (str):         The file path for the mask indicating the region 
                               where areal extent should be recorded. If this 
                               does exist, the mask will be if this is inputted 
                               as a file directory to a jpg file. If the file 
                               does not exist, then the mask generation process 
                               will load and the mask will be saved to the 
                               given directory. If no directory is specified 
                               (i.e. maxMaskPath=None), the images will not be 
                               masked.
    maxim (int):               Image with maximum areal extent to be detected 
                               (for mask generation).     
    band (str):                String denoting the desired image band.
    equal (bool):              Flag denoting whether histogram equalisation is 
                               applied to images (histogram equalisation is 
                               applied if True). Default is True.                          
    loadall (bool):            Flag which, if true, will force all images in 
                               the sequence to be loaded as images (array) 
                               initially and thus not re-loaded in subsequent 
                               processing. 
                               This is only advised for small image sequences. 
    timingMethod (str):        Method for deriving timings from imagery. By 
                               default, timings are extracted from the image 
                               EXIF data.

    Class properties:
    self._maximg (int):        Reference number for image with maximum areal 
                               extent.
    self._pxplot (list):       Pixel plotting extent for easier colourrange 
                               definition and area verification 
                               [xmin, xmax, ymin, ymax].
    self._colourrange (list):  Colour range for automated area detection.
    self._threshold (int):     Maximum number of polygons retained after 
                               initial detection (based on size of polygons).
    self._enhance (list):      Image enhancement parameters for changing 
                               brightness and contrast. This is defined by 
                               three variables, held as a list: 
                               [diff, phi, theta].
                               (1) diff: Inputted as either 'light or 'dark', 
                               signifying the intensity of the image pixels. 
                               'light' increases the intensity such that dark 
                               pixels become much brighter and bright pixels 
                               become slightly brighter. 'dark' decreases the 
                               intensity such that dark pixels become much 
                               darker and bright pixels become slightly darker.
                               (2) phi: Defines the intensity of all pixel 
                               values.
                               (3) theta: Defines the number of "colours" in 
                               the image, e.g. 3 signifies that all the pixels 
                               will be grouped into one of three pixel values.
                               The default enhancement parameters are 
                               ['light', 50, 20].
    self._calibFlag (bool):    Boolean flag denoting whether measurements 
                               should be made on images corrected/uncorrected 
                               for distortion.
    self._pxpoly (arr):        Output pixel coordinates (uv) for detected areas 
                               in an image sequence.
    self._pxextent (list):     Output pixel extents for detected areas in an 
                               image sequence.
    self._realpoly (arr):      Output real-world coordinates (xyz) for detected 
                               areas in an image sequence.
    self._area (list):         Output real-world surface areas for detected 
                               areas in an image sequence.
    '''
    
    #Initialisation of Area class object          
    def __init__(self, imageList, cameraenv, calibFlag=True, band='L', 
                 equal=True):
        
        #Initialise and inherit from the ImageSequence object
        ImageSequence.__init__(self, imageList, band, equal) 
        
        #Set up class properties
        self._camEnv = cameraenv
        self._calibFlag = calibFlag
        self._pxplot = None
        self._maximg = 0
        self._mask = None
        self._enhance = None


    def calcAutoAreas(self, colour=False, verify=False):
        '''Detects areas of interest from a sequence of images, and returns 
        pixel and xyz areas. 
        
        Args
        colour (boolean):           Flag to denote whether colour range for 
                                    detection should be defined for each image
                                    or only once.
        verify (boolean):           Flag to denote whether detected polygons
                                    should be manually verified by user.
    
        Returns
        area (list):                XYZ and UV area information
        '''               
        print '\n\nCOMMENCING AUTOMATED AREA DETECTION' 

        #Get DEM from camera environment
        dem = self._camEnv.getDEM() 

        #Get inverse projection variables through camera info               
        invprojvars = setInvProjVars(dem, self._camEnv._camloc, 
                                     self._camEnv._camDirection, 
                                     self._camEnv._radCorr, 
                                     self._camEnv._tanCorr, 
                                     self._camEnv._focLen, 
                                     self._camEnv._camCen, 
                                     self._camEnv._refImage)
            
        #If user is only defining the color range once
        if colour is False: 
            
            #Define colour range if none is given
            if self._colourrange is None:

                #Get image (either corrected or distorted)
                if self._calibFlag is True:
                    cameraMatrix=self._camEnv.getCamMatrixCV2()
                    distortP=self._camEnv.getDistortCoeffsCV2()
                    setting=self._imageSet[self._maximg].getImageCorr(cameraMatrix, 
                                                               distortP)
                else:
                    setting = self._imageSet[self._maximg].getImageArray() 
    
                #Get image name
                setimn=self._imageSet[self._maximg].getImageName()
                  
                #Get mask and mask image if present
                if self._mask is not None:                       
                    booleanMask = np.array(self._mask, dtype=bool)
                    booleanMask = np.invert(booleanMask)
                    
                    #Mask extent image with boolean array
                    np.where(booleanMask, 0, setting) #Fit arrays to each other
                    setting[booleanMask] = 0 #Mask image with boolean mask object       
                       
                #Enhance image if enhancement parameters given
                if self._enhance is not None:
                    setting = enhanceImage(setting, self._enhance[0], 
                                           self._enhance[1], self._enhance[2])
                
                #Define colour range
                defineColourrange(setting, setimn, pxplot=self._pxplot)    
            
        #Set up output datasets
        area=[]
                       
        #Cycle through image sequence (numbered from 0)
        for i in range(self.getLength()):
            
            #Get corrected/distorted image
            if self._calibFlag is True:
                cameraMatrix=self._camEnv.getCamMatrixCV2()
                distortP=self._camEnv.getDistortCoeffsCV2()
                img1 = self._imageSet[i].getImageCorr(cameraMatrix, 
                                                      distortP)
            else:
                img1=self._imageSet[i].getImageArray()

            #Get image name
            imn=self._imageSet[i].getImageName()
               
            #Make a copy of the image array
            img2 = np.copy(img1)
            
            #Mask image if mask is present
            if self._mask is not None:
                booleanMask = np.array(self._mask, dtype=bool)
                booleanMask = np.invert(booleanMask)
                
                #Mask extent image with boolean array
                np.where(booleanMask, 0, img2) #Fit arrays to each other
                img2[booleanMask] = 0 #Mask image with boolean mask object
            
            #Enhance image if enhancement parameters are present
            if self._enhance is not None:
                img2 = enhanceImage(img2, self._enhance[0], self._enhance[1],
                                    self._enhance[2])
            
            #Define colour range if required
            if colour is True:
                defineColourrange(img2, imn, pxplot=self._pxplot)
            
            #Calculate extent
            out = calcAutoArea(img2, imn, self._colourrange, self._threshold, 
                               invprojvars)  
            
            area.append(out)

            #Clear memory
            self._imageSet[i].clearImage()
            self._imageSet[i].clearImageArray()
        
        #Verify areas if flag is true
        if verify is True:
            area = self.verifyAreas(area, invprojvars)

        #Return all xy coordinates and pixel extents                 
        return area


    def calcManualAreas(self):
        '''Manually define areas of interest in a sequence of images. User 
        input is facilitated through an interactive plot to click around the 
        area of interest
        
        Returns
        area (list):                XYZ and UV area information
        '''                
        '\n\nCOMMENCING MANUAL AREA DETECTION'
            
        #Set up output dataset
        area=[]

        #Get DEM from camera environment
        dem = self._camEnv.getDEM() 

        #Get inverse projection variables through camera info               
        invprojvars = setInvProjVars(dem, self._camEnv._camloc, 
                                     self._camEnv._camDirection, 
                                     self._camEnv._radCorr, 
                                     self._camEnv._tanCorr, 
                                     self._camEnv._focLen, 
                                     self._camEnv._camCen, 
                                     self._camEnv._refImage)
                
        #Cycle through images        
        for i in (range(self.getLength())):
            
            #Call corrected/uncorrected image
            if self._calibFlag is True:
                img=self._imageSet[i].getImageCorr(self._camEnv.getCamMatrixCV2(), 
                                                   self._camEnv.getDistortCoeffsCV2())      
            else:
                img=self._imageSet[i].getImageArray()          

            #Get image name
            imn=self._imageSet[i].getImageName()
            
            #Manually define extent and append
            polys = calcManualArea(img, imn, self._pxplot, invprojvars)       
            area.append(polys)
            
            #Clear memory
            self._imageSet[i].clearImage()
            self._imageSet[i].clearImageArray()
    
        #Return all extents, all cropped images and corresponding image names       
        return area
    
        
    def verifyAreas(self, areas, invprojvars):
        '''Method to manually verify all polygons in images. Plots sequential
        images with detected polygons and the user manually verifies them by 
        clicking them.
        
        Args
        area (list):                XYZ and UV area information
        invprojvars (list):         Inverse projection variables
        
        Returns
        verified (list):            Verified XYZ and UV area information
        '''
        #Create output
        verified = []
        
        #Get UV point coordinates
        uvpts=[item[1][1] for item in areas]
                
        #Verify pixel polygons in each image        
        for i in range(len(uvpts)):
            
            #Call corrected/uncorrected image
            if self._calibFlag is True:
                img1=self._imageSet[i].getImageCorr(self._camEnv.getCamMatrixCV2(), 
                                                    self._camEnv.getDistortCoeffsCV2())      
            else:
                img1=self._imageSet[i].getImageArray()            
            
            #Get image name
            imn=self._imageSet[i].getImageName()
            
            #Verify polygons
            img2 = np.copy(img1)
            
            if 1:                            
                print '\nVerifying detected areas from ' + imn
                
                #Set up empty output list                
                verf = []
                
                #Function for click verification within a plot
                def onpick(event):
                    
                    #Get XY coordinates for clicked point in a plot
                    v = []
                    thisline = event.artist
                    xdata = thisline.get_xdata()
                    ydata = thisline.get_ydata()
                    
                    #Append XY coordinates
                    for x,y in zip(xdata,ydata):
                        v.append([x,y])
                    v2=np.array(v, dtype=np.int32).reshape((len(xdata)),2)
                    verf.append(v2)
                    
                    #Verify extent if XY coordinates coincide with a
                    #detected area
                    ind=event.ind
                    print ('Verified extent at ' + 
                           str(np.take(xdata, ind)[0]) + ', ' + 
                           str(np.take(ydata, ind)[0]))
                
                #Plot image
                fig, ax1 = plt.subplots()
                fig.canvas.set_window_title(imn + ': Click on valid areas.')
                ax1.imshow(img2, cmap='gray')
                
                #Chane plot extent if pxplot variable is present
                if self._pxplot is not None:
                    ax1.axis([self._pxplot[0],self._pxplot[1],
                              self._pxplot[2],self._pxplot[3]])
                
                #Plot all detected areas
                for a in uvpts[i]:
                    x=[]
                    y=[]
                    for b in a:
                        for c in b:
                            x.append(c[0])
                            y.append(c[1])
                    line = Line2D(x, y, linestyle='-', color='y', picker=True)
                    ax1.add_line(line)
                
                #Verify extents using onpick function
                fig.canvas.mpl_connect('pick_event', onpick)
            
            #Show plot
            plt.show()           
            
            #Append all verified extents
            vpx=[]
            vpx=verf               
            
            #Get areas of verified extents
            h = img2.shape[0]
            w = img2.shape[1]
            px_im = Image.new('L', (w,h), 'black')
            px_im = np.array(px_im) 
            cv2.drawContours(px_im, vpx, -1, (255,255,255), 4)
            for p in vpx:
                cv2.fillConvexPoly(px_im, p, color=(255,255,255))           
            output = Image.fromarray(px_im)

            pixels = output.getdata()
            values = []    
            for px in pixels:
                if px > 0:
                    values.append(px)
            pxext = len(values)        
            print 'Total verified extent: ', pxext  

            #Get xyz coordinates with inverse projection
            if invprojvars is not None:
                vxyzpts=[]
                vxyzarea=[]
                for i in vpx:
                    #Inverse project points 
                    proj=invproject(i, invprojvars)           
                    vxyzpts.append(proj)
                    ogrpol = getOGRArea(proj)                   
                    vxyzarea.append(ogrpol.GetArea())
                    
                print 'Total verified area: ', str(sum(vxyzarea)), ' m'            

            verified.append([[pxext, vpx],[vxyzarea, vxyzpts]])                    
            
            #Clear memory            
            self._imageSet[i].clearImage()
            self._imageSet[i].clearImageArray()
        
        #Rewrite verified area data
        return verified
        

    def setMax(self, maxMaskPath, maxim):
        '''Set image in sequence which pictures the maximum extent of the area
        of interest.
        '''
        #Calibrate image if calibration flag is true
        if self._calibFlag is True:
            cameraMatrix=self._camEnv.getCamMatrixCV2()
            distortP=self._camEnv.getDistortCoeffsCV2()
            maxi = self._imageSet[maxim].getImageCorr(cameraMatrix, 
                                                               distortP)
        else:
            maxi = self._imageSet[maxim].getImageArray()
            
        #Define mask on image with maximum areal extent
        self._mask = readMask(maxi, maxMaskPath)
        
        #Retain image sequence number for image with maximum extent
        self._maximg = maxim


    def setPXExt(self,xmin,xmax,ymin,ymax):
        '''Set plotting extent. Setting the plot extent will make it easier to 
        define colour ranges and verify areas.
        
        Args
        xmin (int):               X-axis minimum value.
        xmax (int):               X-axis maximum value.
        ymin (int):               Y-axis minimum value.
        ymax (int):               Y-axis maximum value.
        '''
        self._pxplot = [xmin,xmax,ymin,ymax]


    def setThreshold(self, number):
        '''Set threshold for number of polgons kept from an image.
        
        Args
        number (int):             Number denoting the number of detected 
                                  polygons that will be retained.
        '''
        self._threshold = number
                                

    def setColourrange(self, upper, lower):
        '''Manually define the RBG colour range that will be used to filter
        the image/images.
        
        Args
        upper (int):              Upper value of colour range.
        lower (int):              Lower value of colour range.
        '''      
        print '\nColour range defined from given values:'
        print 'Upper RBG boundary: ', upper
        print 'Lower RBG boundary: ', lower
        
        #Assign colour range
        self._colourrange = [upper, lower]
        

    def setEnhance(self, diff, phi, theta):
        '''Set image enhancement parameters. Change brightness and contrast of 
        image using phi and theta variables.
        Change phi and theta values accordingly. See enhanceImg function for 
        detailed explanation of the parameters.
        
        Args
        diff (str):               Inputted as either 'light or 'dark', 
                                  signifying the intensity of the image pixels. 
                                  'light' increases the intensity such that 
                                  dark pixels become much brighter and bright 
                                  pixels become slightly brighter. 
                                  'dark' decreases the intensity such that dark 
                                  pixels become much darker and bright pixels 
                                  become slightly darker.
        phi (int):                A value between 0 and 1000 which defines the
                                  intensity of all pixel values.
        theta (int):              A value between 0 and 1000 which defines the 
                                  number of "colours" in the image, e.g. 3
                                  signifies that all the pixels will be grouped
                                  into one of three pixel values.
        '''
        self._enhance = diff, phi, theta
 

#------------------------------------------------------------------------------   

def calcAutoArea(img, imn, colourrange, threshold=None, invprojvars=None):
    '''Detects areas of interest from a given image, and returns pixel and xyz 
    areas along with polygon coordinates. Detection is performed from the image 
    using a predefined RBG colour range. The colour range is then used to 
    extract pixels within that range using the OpenCV function inRange. If a 
    threshold has been set (using the setThreshold function) then only nth 
    polygons will be retained. XYZ areas and polygon coordinates are only 
    calculated when a set of inverse projection variables are provided.
    
    Args
    img (arr):            Image array
    imn (str):            Image name
    colourrange (list):   RBG colour range for areas to be detected from
    threshold (int):      Threshold number of detected areas to retain
    invprojvars (list):   Inverse projection variables
    
    Returns
    xyzarea (list):       Sum of total detected areas (xyz)
    xyzpts (list):        XYZ coordinates of detected areas
    pxextent (list):      Sum of total detected areas (px)
    pxpts (list):         UV coordinates of detected areas
    '''                       
    #Get upper and lower RBG boundaries from colour range
    upper_boundary = colourrange[0]
    lower_boundary = colourrange[1]

    #Transform RBG range to array    
    upper_boundary = np.array(upper_boundary, dtype='uint8')
    lower_boundary = np.array(lower_boundary, dtype='uint8')

    #Extract extent based on RBG range
    mask = cv2.inRange(img, lower_boundary, upper_boundary)

#    #Speckle filter to remove noise - needs fixing
#    mask = cv2.filterSpeckles(mask, 1, 30, 2)

    #Polygonize extents using OpenCV findContours function        
    polyimg, line, hier = cv2.findContours(mask, cv2.RETR_EXTERNAL, 
                                           cv2.CHAIN_APPROX_NONE)
    
    print '\nDetected ' + str(len(line)) + ' regions in ' + imn
    
    #Append all polygons from the polys list that have more than 
    #a given number of points     
    pxpts = []
    for c in line:
        if len(c) >= 40:
            pxpts.append(c)
    
    #If threshold has been set, only keep the nth longest polygons
    if threshold is not None:
        if len(pxpts) >= threshold:
            pxpts.sort(key=len)
            pxpts = pxpts[-(threshold):]        

    print 'Kept %d regions' % (len(pxpts))
    
    #Calculate areas
    pxextent=[]
    for p in range(len(pxpts)): 

        try:        
            #Create geometry
            pxpoly=getOGRArea(pxpts[p].squeeze())
            
            #Calculate area of polygon area
            pxextent.append(pxpoly.Area())
        
        #Create zero object if no polygon has been recorded 
        except:
            pxextent = 0
        
    print ('Total extent: ' + str(sum(pxextent)) + 'px (out of ' 
            + str(img.shape[0]*img.shape[1]) + 'px)')  
    
    #Get xyz coordinates with inverse projection
    if invprojvars is not None:
        xyzpts=[]
        xyzarea=[]
        
        for i in pxpts:           
            #Inverse project points 
            proj=invproject(i, invprojvars)           
            xyzpts.append(proj)
            
            #Get areas for xyz polygons
            ogrpol = getOGRArea(proj)                   
            xyzarea.append(ogrpol.GetArea())
            
        print 'Total area: ', str(sum(xyzarea)), 'm'
                
        #Return XYZ and pixel areas
        return [[xyzarea, xyzpts], [pxextent, pxpts]]
    
    else:
        #Return pixel areas only
        return [[None, None], [pxextent, pxpts]]
        

def calcManualArea(img, imn, pxplot=None, invprojvars=None):
    '''Manually define an area in a given image. User input is facilitated
    through an interactive plot to click around the area of interest. XYZ areas
    are calculated if a set of inverse projection variables are given.
    
    Args
    img (arr):          Image array (for plotting the image).
    imn (str):          Image name
    pxplot (list):      Plotting extent for manual area definition
    invprojvars (list): Inverse projection variables
    
    Returns
    xyzarea (list):       Sum of total detected areas (xyz)
    xyzpts (list):        XYZ coordinates of detected areas
    pxextent (list):      Sum of total detected areas (px)
    pxpts (list):         UV coordinates of detected areas
    '''    
    #Initialise figure window and plot image
    fig=plt.gcf()
    fig.canvas.set_window_title(imn + ': Click around region. Press enter '
                                'to record points.')
    plt.imshow(img, origin='upper', cmap='gray')
    
    #Set plotting extent if required
    if pxplot is not None:
        plt.axis([pxplot[0],pxplot[1],
                  pxplot[2],pxplot[3]]) 
    
    #Manual input of points from clicking on plot using pyplot.ginput
    pxpts = plt.ginput(n=0, timeout=0, show_clicks=True, mouse_add=1, 
                    mouse_pop=3, mouse_stop=2)
    print '\n' + imn + ': you clicked ' + str(len(pxpts)) + ' points'
    
    #Show plot
    plt.show()
    plt.close()
        
    #Create polygon if area has been recorded   
    try:
        
        #Complete the polygon ring             
        pxpts.append(pxpts[0]) 
        
        #Create geometry
        pxpoly=getOGRArea(pxpts)
        
        #Calculate area of polygon area
        pxextent = pxpoly.Area()
    
    #Create zero object if no polygon has been recorded 
    except:
        pxextent = 0
    
    print ('Total extent: ' + str(pxextent) + 'px (out of ' 
            + str(img.shape[0]*img.shape[1]) + 'px)')    
    
    #Convert pts list to array
    pxpts = np.array(pxpts)           
    pxpts = np.squeeze(pxpts)
    

    if invprojvars is not None:
        #Get xyz coordinates with inverse projection
        xyzpts=invproject(pxpts, invprojvars) 
        
        #Calculate area of xyz polygon
        xyzarea = getOGRArea(xyzpts)                   
        xyzarea=xyzarea.GetArea()
        
        #Return XYZ and pixel areas
        print 'Total area: ', str(xyzarea), 'm'
        return [[[xyzarea], [xyzpts]], [[pxextent], [pxpts]]]

    #Return pixel areas only    
    else:
        return [[None, None], [pxextent, pxpts]]          


def defineColourrange(img, imn, pxplot=None):
    '''Define colour range manually by clicking on the lightest and 
    darkest regions of the target extent that will be defined.
    
    Plot interaction information:
        Left click to select.
        Right click to undo selection.
        Close the image window to continue.
        The window automatically times out after two clicks
    
    Args
    img (arr):                  Image array (for plotting the image)
    imn (str):                  Image name
    
    Returns:
    upper_boundary (int):       Upper RGB range for detection
    lower_boundary (int):       Lower RGB range for detection
    '''
    #Initialise figure window
    fig=plt.gcf()
    fig.canvas.set_window_title(imn + ': Click lightest colour and darkest' 
                                ' colour')
    
    #Plot image
    plt.imshow(img, origin='upper')
    
    #Define plotting extent if required
    if pxplot is not None:
        plt.axis([pxplot[0],pxplot[1],pxplot[2],pxplot[3]])

    #Manually interact to select lightest and darkest part of the region            
    colours = plt.ginput(n=2, timeout=0, show_clicks=True, mouse_add=1, 
                        mouse_pop=3, mouse_stop=2)
    
    print '\n' + imn + ': you clicked ', colours
    
    #Show plot
    plt.show()
    
    #Get pixel intensity value for pt1       
    col1_rbg = img[colours[0][1],colours[0][0]]
    if col1_rbg == 0:
        col1_rbg=1

    #Get pixel intensity value for pt2        
    col2_rbg = img[colours[1][1],colours[1][0]]
    if col2_rbg == 0:
        col2_rbg=1
        
    #Assign RBG range based on value of the chosen RBG values
    if col1_rbg > col2_rbg:
        upper_boundary = col1_rbg
        lower_boundary = col2_rbg
    else:
        upper_boundary = col2_rbg
        lower_boundary = col1_rbg
    
    print '\nColour range found from manual selection'
    print 'Upper RBG boundary: ' + str(upper_boundary)
    print 'Lower RBG boundary: ' + str(lower_boundary)

    #Return RBG range
    return [upper_boundary, lower_boundary]
   
    
def getOGRArea(pts):
    '''Get real world OGR polygons (.shp) from xyz poly pts with real world 
    points which are compatible with mapping software (e.g. ArcGIS).
    
    Args
    pts (arr):                UV/XYZ coordinates of a given area shape
    
    Returns
    polygons (list):          OGR geometry polygon                           
    '''                       
    #Create geometries from uv/xyz coordinates using ogr                     
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for p in pts:
        if np.isnan(p[0]) == False:
            if len(p)==2:
                ring.AddPoint(int(p[0]),int(p[1]))
            else:                  
                ring.AddPoint(p[0],p[1],p[2])
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly