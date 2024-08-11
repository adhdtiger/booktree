
from dataclasses import dataclass
from dataclasses import field
import os, sys, subprocess, shlex, re
from pprint import pprint
import json
import posixpath
import myx_utilities
import myx_audible
import myx_args
import myx_mam

#Module variables
authMode="login"
verbose=False

#Author and Narrator Classes
@dataclass
class Contributor:
    name:str
    #books:list[int]= field(default_factory=list)

#Series Class
@dataclass
class Series:
    name:str=""
    part:str=""
    
    def getSeriesPart(self):
        if (len(self.part.strip()) > 0):
            return "{} #{}".format(self.name, str(self.part))
        else:
            return self.name

#Book Class
@dataclass
class Book:
    asin:str=""
    title:str=""
    subtitle:str=""
    publicationName:str=""
    length:int=0
    duration:str=""
    matchRate=0
    series:list[Series]= field(default_factory=list)
    authors:list[Contributor]= field(default_factory=list)
    narrators:list[Contributor]= field(default_factory=list)
    files:list[str]= field(default_factory=list)

    def addFiles(self, file):
        self.files.append(file)

    def getFullTitle(self, field="subtitle"):
        title=""
        if field == "series":
            if (len(self.series) > 0):
                title= self.title + ": " + self.series[0].getSeriesPart()
        else:
            title=self.title + ": " + self.subtitle
        
        return title
    
    def getCleanTitle(self):
        #Removes (Unabdridged from the title)
        return self.title.replace (" (Unabridged)","")
    
    def getAuthors(self, delimiter=",", encloser="", stripaccents=True):
        if len(self.authors):
            return myx_utilities.getList(self.authors, delimiter, encloser, stripaccents=True)
        else:
            return ""
    
    def getSeries(self, delimiter=",", encloser="", stripaccents=True):
        if len(self.series):
            return myx_utilities.getList(self.series, delimiter, encloser, stripaccents=True)
        else:
            return ""
    
    def getNarrators(self, delimiter=",", encloser="", stripaccents=True):
        if len(self.narrators):
            return myx_utilities.getList(self.narrators, delimiter, encloser, stripaccents=True) 
        else:
            return ""
    
    def getSeriesParts(self, delimiter=",", encloser="", stripaccents=True):
        seriesparts = []
        for s in self.series:
            if len(s.name.strip()):
                seriesparts.append(Contributor(f"{s.name} #{s.part}")) 
            
        return myx_utilities.getList(seriesparts, delimiter, encloser, stripaccents=True) 
    
    def setAuthors(self, authors):
        #Given a csv of authors, convert it to a list
        if len(authors.strip()):
            for author in list([authors]):
                self.authors.append(Contributor(author))

    def setSeries(self, series):
        #Given a csv of authors, convert it to a list
        if len(series.strip()):
            for s in list([series]):
                p = s.split("#")
                if len(p) > 1: 
                    self.series.append(Series(str(p[0]).strip(), str(p[1]).strip()))
                else:
                    self.series.append(Series(str(p[0]).strip(), ""))
            
    def getDictionary(self, book, ns=""):
        book[f"{ns}matchRate"]=self.matchRate
        book[f"{ns}asin"]=self.asin
        book[f"{ns}title"]=self.title
        book[f"{ns}subtitle"]=self.subtitle
        book[f"{ns}publicationName"]=self.publicationName
        book[f"{ns}length"]=self.length
        book[f"{ns}duration"]=self.duration
        book[f"{ns}series"]=self.getSeries()
        book[f"{ns}authors"]=self.getAuthors()
        book[f"{ns}narrators"]=self.getNarrators()
        book[f"{ns}seriesparts"]=self.getSeriesParts()
        return book  
    
    def init(self):
        self.asin=""
        self.title=""
        self.subtitle=""
        self.publicationName=""
        self.duration=""
        self.series=[]
        self.authors=[]
        self.narrators=[]

    def getAllButTitle(self):
        book={}
        book=self.getDictionary(book)
        book["title"]=""
        return book
          
#Book File Class
@dataclass
class BookFile:
    file:posixpath
    fullPath:str
    sourcePath:str
    isMatched:bool=False
    isHardlinked:bool=False
    audibleMatch:Book=None
    ffprobeBook:Book=None
    #audibleMatches:dict=field(default_factory=dict)
    audibleMatches:list[Book]= field(default_factory=list)

    def getExtension(self):
        return os.path.splitext(self.file)[1].replace(".","")

    def hasNoParentFolder(self):
        return (len(self.getParentFolder())==0)
    
    def getParentFolder(self):
        return myx_utilities.getParentFolder(self.file, self.sourcePath)

    def getFileName(self):
        return os.path.basename(self.file)
        
    def __probe_file(self):
        #ffprobe -loglevel error -show_entries format_tags=artist,album,title,series,part,series-part,isbn,asin,audible_asin,composer -of default=noprint_wrappers=1:nokey=0 -print_format compact "$file")
        cmnd = ['ffprobe','-loglevel','error','-show_entries','format_tags=artist,album,title,series,part,series-part,isbn,asin,audible_asin,composer', '-of', 'default=noprint_wrappers=1:nokey=0', '-print_format', 'json', self.fullPath]
        p = subprocess.Popen(cmnd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err =  p.communicate()
        return json.loads(out)
    
    def ffprobe(self):
        #ffprobe the file
        try:
            metadata=self.__probe_file()["format"]["tags"]
        except Exception as e:
            metadata=dict()
            if myx_args.params.verbose:
                print (f"ffprobe failed on {self.file}: {e}")

        #parse and create a book object
        # format|tag:title=In the Likely Event (Unabridged)|tag:artist=Rebecca Yarros|tag:album=In the Likely Event (Unabridged)|tag:AUDIBLE_ASIN=B0BXM2N523
        #{'format': {'tags': {'title': 'MatchUp', 'artist': 'Lee Child - editor, Val McDermid, Charlaine Harris, John Sandford, Kathy Reichs', 'composer': 'Laura Benanti, Dennis Boutsikaris, Gerard Doyle, Linda Emond, January LaVoy, Robert Petkoff, Lee Child', 'album': 'MatchUp'}}}
        book=Book()
        if 'AUDIBLE_ASIN' in metadata: book.asin=metadata["AUDIBLE_ASIN"]
        if 'title' in metadata: book.title=metadata["title"]
        if 'subtitle' in metadata: book.subtitle=metadata["subtitle"]
        #series and part, if provided
        if (('SERIES' in metadata) and ('PART' in metadata)): 
            book.series.append(Series(metadata["SERIES"],metadata["PART"]))
        #parse album, assume it's a series
        if 'album' in metadata: book.series.append(Series(metadata["album"],""))
        #parse authors
        if 'artist' in metadata: 
            for author in metadata["artist"].split(","):
                book.authors.append((Contributor(myx_utilities.removeGA(author))))
        #parse narrators
        if 'composer' in metadata: 
            for narrator in metadata["composer"].split(","):
                book.narrators.append(Contributor(narrator))
        #return a book object created from  ffprobe
        self.ffprobeBook=book
        if verbose:
            pprint (book)
        return book
    
    def __getAudibleBook(self, product):
        #product is an Audible product json
        if product is not None:
            book=Book()
            if 'asin' in product: book.asin=product["asin"]
            if 'title' in product: book.title=product["title"]
            if 'subtitle' in product: book.subtitle=product["subtitle"]
            if 'runtime_length_min' in product: book.length=product["runtime_length_min"]
            if 'authors' in product: 
                for author in product["authors"]:
                    book.authors.append(Contributor(author["name"]))
            if 'narrators' in product: 
                for narrator in product["narrators"]:
                    book.narrators.append(Contributor(narrator["name"]))
            if 'publication_name' in product: book.publicationName=product["publication_name"]
            if 'relationships' in product: 
                for relationship in product["relationships"]:
                    #if this relationship is a series
                    if (relationship["relationship_type"] == "series"):
                        book.series.append(Series(relationship["title"], relationship["sequence"]))
            pprint (book)
            return book
        else:
            return None
        
    def matchBook(self, client, matchRate=75):
        #given book file, ffprobe and audiblematches, return the best match
        parent = myx_utilities.getParentFolder(self.fullPath,self.sourcePath).replace(" (Unabridged)", "")

        #first, read the ID tags
        ffprobeBook=self.ffprobe()
        asin=ffprobeBook.asin
        keywords=myx_utilities.optimizeKeys([parent])

        #catalog/products asin, author, title, keywords
        # books=getAudibleBook(client, asin, ffprobeBook.getAuthors(), parent, keywords)
        # if books is not None:
        #     print ("Found {} books".format(len(books)))
        #     for book in books:
        #         self.audibleMatches[book["asin"]]=self.__getAudibleBook(book)

        # Strategy#1:  If an ASIN was in the ID Tag, search by ASIN
        if len(ffprobeBook.asin) > 0:
            print ("Getting Book by ASIN ", ffprobeBook.asin)
            book=self.__getAudibleBook(myx_audible.getBookByAsin(client, ffprobeBook.asin))
            if ((book is not None) and (myx_utilities.fuzzymatch(ffprobeBook.title, book.title) > matchRate)):
                self.audibleMatch=book
                self.isMatched=True

        # Strategy #2:  ASIN search was a bust, try a wider search (Author, Title, Keywords)
        #asin might be available but a match wasn't found, try Author/Title Search        
        if (not self.isMatched):
            fBook=""

            #check if an author was found
            if (len(ffprobeBook.authors) == 0):
                author=""
            else:
                author=ffprobeBook.authors[0].name

            #Use Case:  If title or author are missing, perform a keyword search with whatever is available with the ID3 tags
            if ((len(author)==0) and len(ffprobeBook.title) ==0):
                keywords=myx_utilities.optimizeKeys([parent],",")
                # Option #1: find book by artist or title (using parent folder)
                print ("No ID3 tags Getting Book by Parent Folder: {}".format(keywords))
                books=myx_audible.getAudibleBook(client, keywords=keywords)
                if books is not None:
                    print ("Found {} books".format(len(books)))
                    for book in books:
                        self.audibleMatches[book["asin"]]=self.__getAudibleBook(book)
                        #self.audibleMatches.append(self.__getAudibleBook(book))
                # For Fuzzy Match, just use Keywords
                fBook=keywords
            else:
                #there's at least some metadata available
                #fBook="{},{},{},{},{}".format(ffprobeBook.title,ffprobeBook.subtitle, ffprobeBook.getAuthors("|"), ffprobeBook.getNarrators("|"),ffprobeBook.getSeriesParts())

                #Use Case : Clean ID3, there's an author, a title, a narrator
                if (len(ffprobeBook.title)):
                    keywords=myx_utilities.optimizeKeys([ffprobeBook.getAuthors(),ffprobeBook.getNarrators()])
                    print ("Getting Book by Title:{} & Keywords:'{}'".format(ffprobeBook.title, keywords))
                    books=myx_audible.getAudibleBook(client, title=ffprobeBook.title, keywords=keywords)
                    if books is not None:
                        print ("Found {} books".format(len(books)))
                        fBook="{},{}".format(ffprobeBook.title, keywords)
                        for book in books:
                            #self.audibleMatches[book["asin"]]=self.__getAudibleBook(book)
                            self.audibleMatches.append(self.__getAudibleBook(book))             

                if (len(self.audibleMatches) == 0):
                    #Use Case: Author, Title, Narrator is too narrow - we're putting these values as keywords with the folder name
                    if (len(ffprobeBook.title)):
                        keywords=myx_utilities.optimizeKeys([parent,ffprobeBook.getAuthors()])
                        print ("Getting Book by Keyword using Parent Folder/Author/Title as keywords {}".format(keywords))
                        books=myx_audible.getAudibleBook(client, title=ffprobeBook.title, keywords=keywords)
                        if books is not None:
                            print ("Found {} books".format(len(books)))
                            fBook="{},{},{}".format(parent,ffprobeBook.title,ffprobeBook.getAuthors())
                            for book in books:
                                #self.audibleMatches[book["asin"]]=self.__getAudibleBook(book)
                                self.audibleMatches.append(self.__getAudibleBook(book))             

                    #Use Case: Clean ID3, but didn't find a match, try a wider search - normally because it's a multi-file book and the parent folder is the title
                    if (len(self.audibleMatches) == 0):
                        print ("Performing wider search...")

                        # Use Case: ID3 has the author, the parent folder is ONLY the title
                        print ("Getting Book by Parent Folder Title: {}".format(parent))
                        #books=getBookByAuthorTitle(client, author, parent)
                        keywords=myx_utilities.optimizeKeys([parent])
                        books=myx_audible.getAudibleBook(client, keywords=keywords)                        
                        if books is not None:
                            print ("Found {} books".format(len(books)))
                            fBook=parent
                            for book in books:
                                #self.audibleMatches[book["asin"]]=self.__getAudibleBook(book)
                                self.audibleMatches.append(self.__getAudibleBook(book))
                        
                        # Use Case:  ID3 has the author, and the album is the title
                        if (len(ffprobeBook.series) > 0):
                            print ("Getting Book by Album Title: {}, {}".format(author, ffprobeBook.series[0].name))
                            if (len(ffprobeBook.series) > 0):
                                books=myx_audible.getBookByAuthorTitle(client, author, ffprobeBook.series[0].name)
                                if books is not None:
                                    print ("Found {} books".format(len(books)))
                                    fBook+=",{},{}".format(author, ffprobeBook.series[0].name)
                                    for book in books:
                                        #self.audibleMatches[book["asin"]]=self.__getAudibleBook(book)
                                        self.audibleMatches.append(self.__getAudibleBook(book)) 

            # check if there's an actual Match from Audible
            # if there's exactly 1 match, assume it's good
            if (len(self.audibleMatches) == 1):
                for i in self.audibleMatches:
                    self.audibleMatch=i
                    self.isMatched=True
            else:
                print ("Finding the best match out of {}".format(len(self.audibleMatches)))
                if (len(self.audibleMatches) > 1):
                    #find the highest match, start with 0
                    bestMatchRatio=0
                    bestMatchedBook=None
                    for book in self.audibleMatches:
                        #do fuzzymatch with all these combos, get the highest value
                        aBook="{},{},{}".format(book.title,book.getAuthors("|"),book.getSeriesParts("|"))
                        matchRatio=myx_utilities.fuzzymatch(fBook,aBook)

                        #set this books matchRatio
                        book.matchRate=matchRatio
                        
                        if (matchRatio > bestMatchRatio):
                            print("Found a better match!{} > {}", matchRatio, bestMatchRatio)
                            #this is the new best
                            bestMatchRatio = matchRatio
                            bestMatchedBook = book

                    if (bestMatchRatio > matchRate):
                        self.isMatched=True
                        self.audibleMatch=bestMatchedBook
                        print ("{} Match found: {}".format(bestMatchRatio, bestMatchedBook.title))
 
    def hardlinkFile(self, source, target):
        #add target to base Media folder
        destination = os.path.join("/data/media/audiobooks/mam", target)
        #print ("Destination {}-{}".format(destination, os.path.join("/data/media/audiobooks/test", target)))
        #check if the target path exists
        if (not os.path.exists(destination)):
            #make dir path
            print ("Creating target directory ", destination)
            os.makedirs(destination)
        
        #check if the file already exists in the target directory
        filename=os.path.join(destination, os.path.basename(source).split('/')[-1])
        if (not os.path.exists(filename)):
            print ("Hardlinking {} to {}".format(source, filename))
            try:
                os.link(source, filename)
                self.isHardlinked=True
            except Exception as e:
                print ("Failed to hardlink {} to {} due to:".format(source, filename, e))

        return self.isHardlinked
    
    def getTargetPaths(self, book):
        paths=[]
        if (book is not None):
            #Get primary author
            if ((book.authors is not None) and (len(book.authors) == 0)):
                author="Unknown"
            else:
                author=book.authors[0].name  

            #standardize author name (replace . with space, and then make sure that there's only single space)
            stdAuthor=myx_utilities.cleanseAuthor(author)

            #Does this book belong in a series?
            if (len(book.series) > 0):
                for s in book.series:
                    paths.append("{}/{}/{} - {}/".format(stdAuthor, s.name, s.getSeriesPart(), book.title))
            else:
                paths.append("{}/{}/".format(stdAuthor, book.title))   

        return paths  
    
    def getLogRecord(self, bookMatch:Book):
        #returns a dictionary of the record that gets logged
        book={
            "file":self.fullPath,
            "isMatched": self.isMatched,
            "isHardLinked": self.isHardlinked,
        }

        book=bookMatch.getDictionary(book)
        book["paths"]=",".join(self.getTargetPaths(bookMatch))

        return book
    
@dataclass
class MAMBook:
    name:str
    files:list= field(default_factory=list) 
    ffprobeBook:Book=None
    bestAudibleMatch:Book=None 
    bestMAMMatch:Book=None
    mamMatches:list[Book]= field(default_factory=list)    
    audibleMatches:list[Book]= field(default_factory=list)  
    isSingleFile:bool=False
    isMultiFileBook:bool=False
    isMultiBookCollection:bool=False
    metadata:str="id3"
    metadataBook:Book=None

    def ffprobe(self, file):
        #ffprobe the file
        metadata=None
        book=None
        
        try:
            metadata=myx_utilities.probe_file(file)["format"]["tags"]
        except Exception as e:
            if myx_args.params.verbose:
                print (f"ffprobe failed on {self.name}: {e}")

        if (metadata is not None):
            #parse and create a book object
            # format|tag:title=In the Likely Event (Unabridged)|tag:artist=Rebecca Yarros|tag:album=In the Likely Event (Unabridged)|tag:AUDIBLE_ASIN=B0BXM2N523
            #{'format': {'tags': {'title': 'MatchUp', 'artist': 'Lee Child - editor, Val McDermid, Charlaine Harris, John Sandford, Kathy Reichs', 'composer': 'Laura Benanti, Dennis Boutsikaris, Gerard Doyle, Linda Emond, January LaVoy, Robert Petkoff, Lee Child', 'album': 'MatchUp'}}}
            book=Book()
            if 'AUDIBLE_ASIN' in metadata: book.asin=metadata["AUDIBLE_ASIN"]
            if 'title' in metadata: book.title=metadata["title"]
            if 'subtitle' in metadata: book.subtitle=metadata["subtitle"]
            #series and part, if provided
            if (('SERIES' in metadata) and ('PART' in metadata)): 
                book.series.append(Series(metadata["SERIES"],metadata["PART"]))
            #parse album, assume it's a series
            if 'album' in metadata: book.series.append(Series(metadata["album"],""))
            #parse authors
            if 'artist' in metadata: 
                for author in metadata["artist"].split(","):
                    book.authors.append(Contributor(myx_utilities.removeGA(author)))
            #parse narrators
            if 'composer' in metadata: 
                for narrator in metadata["composer"].split(","):
                    book.narrators.append(Contributor(narrator))
        
        #return a book object created from  ffprobe
        self.ffprobeBook=book
        if verbose:
            pprint (book)
        return book

    def getTargetPaths(self, authors, series, title):
        paths=[]
        #Get primary author
        if ((authors is not None) and (len(authors) == 0)):
            author="Unknown"
        else:
            author=authors[0].name  

        #standardize author name (replace . with space, and then make sure that there's only single space)
        stdAuthor=myx_utilities.cleanseAuthor(author)

        #Does this book belong in a series?
        if (len(series) > 0):
            for s in series:
                paths.append("{}/{}/{} - {}/".format(stdAuthor, s.name, myx_utilities.cleanseSeries(s.getSeriesPart()), title))
        else:
            paths.append("{}/{}/".format(stdAuthor, title))   
        return paths  

    def getAudibleBooks(self, client):
        books=[]
        
        #Search Audible using either MAM (better) or ffprobe metadata
        if (self.bestMAMMatch is not None):
            book = self.bestMAMMatch
            title = book.getCleanTitle()
        else:
            book = self.ffprobeBook     
            if (self.isMultiFileBook):
                title = myx_utilities.cleanseTitle(book.getSeries())
            else:
                title = myx_utilities.cleanseTitle(book.title)

        #pprint(book)
        
        keywords=myx_utilities.optimizeKeys([title, book.getSeries()])
        print(f"Searching Audible for\n\tasin:{book.asin}\n\ttitle:{title}\n\tauthors:{book.authors}\n\tkeywords:{keywords}")
        #search each author until a match is found
        for author in book.authors:
            sAuthor=myx_utilities.cleanseAuthor(author.name)
            books=myx_audible.getAudibleBook (client, asin=book.asin, title=title, authors=sAuthor, keywords=keywords)

            #book found, exit for loop
            if ((books is not None) and len(books)):
                break
        
        self.audibleMatches=books
        if (self.audibleMatches is not None):
            if (myx_args.params.verbose):
                    print(f"Found {len(self.audibleMatches)} Audible match(es)\n\n")

            if (len(self.audibleMatches) > 1):
                #find the best match
                #for each matched book, calculate the fuzzymatch rate
                mamBook = '|'.join([book.getCleanTitle(), book.getAuthors(), book.getSeriesParts()])
                bestMatchRate=0
                for product in books:
                    book=myx_audible.product2Book(product)
                    audibleBook = '|'.join([book.getCleanTitle(), book.getAuthors(), book.getSeriesParts()])
                    matchRate=myx_utilities.fuzzymatch(mamBook, audibleBook)
                    book.matchRate=matchRate

                    #is this better?
                    if (matchRate > bestMatchRate):
                        bestMatchRate=matchRate
                        self.bestAudibleMatch=book
            else:
                #the only match is the best match
                if ((books is not None) and (len(books))):
                    self.bestAudibleMatch=myx_audible.product2Book(books[0])

        #pprint(self.bestAudibleMatch)
        if (books is not None): 
            return len(books) 
        else: 
            return 0
        
    def createHardLinks(self, targetFolder, dryRun=False):

        match self.metadata:

            case "audible": self.metadataBook=self.bestAudibleMatch

            case "mam": self.metadataBook=self.bestMAMMatch

            case _: self.metadataBook=self.ffprobeBook

        if (self.metadataBook is not None):
            if myx_args.params.verbose:
                print (f"Hardlinking files for {self.metadataBook.title}")
            
            #for each file for this book                
            for f in self.files:
                #if a book belongs to multiple series, hardlink them to all series
                for p in f.getTargetPaths(self.metadataBook):
                    if (not dryRun):
                        f.hardlinkFile(f.fullPath, os.path.join(targetFolder, myx_utilities.cleanseSeries(p)))
                    
                    if myx_args.params.verbose:
                        print (f"Hardlinking {f.fullPath} to {os.path.join(targetFolder,myx_utilities.cleanseSeries(p))}")
                f.isHardLinked=True
                
                if myx_args.params.verbose:
                    myx_utilities.printDivider()

    def isMatched(self):
        return bool(((self.bestMAMMatch is not None) or (self.bestAudibleMatch is not None)))
    
    def getLogRecord(self, bf):
        #MAMBook fields
        book={}
        book["book"]=self.name
        book["file"]=bf.fullPath
        book["isMatched"]=self.isMatched() 
        book["isHardLinked"]= bf.isHardlinked
        book["mamCount"]=len(self.mamMatches)
        book["audibleMatchCount"]=len(self.audibleMatches)
        book["metadatasource"]=self.metadata
        #check out the targetpath of the first bookfile
        book["paths"]=self.files[0].getTargetPaths(self.metadataBook)

        #Get FFProbe Book
        if (bf.ffprobeBook is not None):
            book=bf.ffprobeBook.getDictionary(book, "id3-")

        #Get MAM Book
        if (self.bestMAMMatch is not None):
            book=self.bestMAMMatch.getDictionary(book, "mam-")

        #Get Audible Book
        if (self.bestAudibleMatch is not None):
            book=self.bestAudibleMatch.getDictionary(book, "adb-")

        return book    

    def getMAMBooks(self, session, bookFile:BookFile):
        #search MAM record for this book
        title=" | ".join([f'"{myx_utilities.cleanseTitle(self.name, stripaccents=False, stripUnabridged=False)}"', 
                          f'"{myx_utilities.cleanseTitle(bookFile.ffprobeBook.title, stripaccents=False, stripUnabridged=False)}"',
                          f'"{bookFile.getFileName()}"'])
        authors=self.ffprobeBook.getAuthors(delimiter="|", encloser='"', stripaccents=False)
        extension = f'"{bookFile.getExtension()}"'
        
        #if this is a single or normal file, do a filename search
        # if (not self.isMultiBookCollection):
        #     titleFilename = f'"{bookFile.getFileName()}"'
        #     if (myx_args.params.metadata == "log"):
        #         #user must have cleaned the id3 tags, use that instead of the book.name
        #         titleFilename.join(f" {bookFile.ffprobeBook.title}")
        # else:
        #     #if this is a multi-file book, use book name and author
        #     titleFilename=title
     
        # Search using book key and authors (using or search in case the metadata is bad)
        print(f"Searching MAM for\n\tTitleFilename: {title}\n\tauthors:{authors}")
        self.mamMatches=myx_mam.getMAMBook(session, titleFilename=title, authors=authors, extension=extension)

        # was the author inaccurate? (Maybe it was LastName, FirstName or accented)
        # print (f"Trying again because Filename, Author = {len(self.mamMatches)}")
        if len(self.mamMatches) == 0:
            #try again, without author this time
            print(f"Widening MAM search using just\n\tTitleFilename: {title}")
            self.mamMatches=myx_mam.getMAMBook(session, titleFilename=title, extension=extension)

        # # print (f"Trying again because Filename = {len(self.mamMatches)}")
        # if len(self.mamMatches) == 0:
        #     #try again, with the parent folder and author
        #     titleFilename = title 
        #     print(f"Widening MAM search using\n\tTitle: {title}\n\tAuthors: {authors}")
        #     self.mamMatches=myx_mam.getMAMBook(session, titleFilename=title, authors=authors, extension=extension)

        if myx_args.params.verbose:
            print(f"Found {len(self.mamMatches)} MAM match(es)\n\n")
        
        #find the best match
        if (len(self.mamMatches) > 1):
            self.bestMAMMatch=myx_utilities.findBestMatch(self.ffprobeBook, self.mamMatches)
        else:
            if (len(self.mamMatches)):
                self.bestMAMMatch=self.mamMatches[0]

        return len(self.mamMatches)
    



