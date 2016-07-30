# Example of computation with Sagemath over Slurm

This is an attempt to document how to use the 
[slurm](https://slurm.schedmd.com/) facilities on a cluster to
run [Sage](https://www.sagemath.org) code in parallel in many nodes. It was 
written mainly to avoid others the time of googling and trial-and-error that I 
had to go through to figure it out.

Most of what is said here can be translated to other software systems that 
support mpi, like plane python, custom .c code and so on. But for the sake of 
clarity, in this document we will restrict ourselves to this particular example 
that involves sage.

I have no experience with other workload mangers, but I imagine that most of 
them will work in a similar way, so it is likely that some minor adaptations of 
the workflow explained here would work with them too.

The goal of this example was, besides testing the cluster infraestucture, to 
double check the values of the HOMFLY polynomial available in the [knot 
atlas](http://katlas.org/) with the implementation available in sage. 

## Quick start

If you just want to test the example, you just need the following:

- An account in a cluster with enough nodes and cpus (the example is configured 
for 3 nodes with 24 pus each one). With the following software installed:
  - The [slurm](https://slurm.schedmd.com/) workload manger
  - An implementation of mpi (in our case, it was 
[OpenMPI](https://www.open-mpi.org/))
  - A recent installation of [Sagemath](https://www.sagemath.org) (in 
particular, some code in our example needs version 7.3beta9 or later). It must 
have the following optional packages installed too:
      - [`mpi4py`](https://pythonhosted.org/mpi4py/)- The library that allows 
python to work with the system MPI.
      - [`libhomfly`](https://github.com/miguelmarco/libhomfly) (this is needed 
for this example, but not in general)
- The following files for this example (you can adapt them for your particular 
case):
  - A small acript to tell slurm what resourecs to allocate and which program 
must be tun (in our case, it is the `batchscript.sh` file).
  - A file with the sage code you want to run. In our example it is the 
`script.py` file.
  - Some files with the input data to feed your computations (if needed). In 
this case, it is the file `Rolfsen.rdf`, that contains the data of the knot 
atlas about the knots in the Rolfsen table. (Taken from the knot atlas web 
page).
    


Once you have it all in a directory of the server that controls de cluster, you 
just have to get a console in that directory and type

```
sbatch batchscript.sh
```

And that is it. Your work will be appended to the queue, it will be run when 
there are available resources, and the output will be written to the file that 
you configured it to.

Let's now see with more detail what do these files contain.

## The slurm script

It is the file in which we tell slurm what resources we want to allocate, and 
what programs we want to run in those resources. Our particular example is the 
file `batchscript.sh`:

```
#!/bin/sh
#SBATCH -o output
#SBATCH --nodes=3
#SBATCH --ntasks-per-node=24
mpirun sage script.py
```

It is actually quite simple. The first line just tells that it is a shell 
script. The lines

```
#SBATCH -o output
#SBATCH --nodes=3
#SBATCH --ntasks-per-node=24
```

stablish the file where the output will be written, the nodes we want to use, 
and how many instances if our program will run in each of them (in our case, we 
have 24 CPU's per node, so we use all of them, 72 processes in total).

Finally the line

```
mpirun sage script.py
```

Tells that the work to be run in those nodes is the sage command, under a mpi 
envornment, running the code in the file `script.py`.

## The actual sage code


### Setting up the environment

Let's now take a look at the actual sage code that we are going to run. It is 
contained in the `script.py` file. It starts with some lines to import the 
necessary modules and set up some global variables that we will need:

```python
from sage.all import *

from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.size
```

the first line imports the whole sage library. That is needed because we are 
executing a `.py` file passed as a parameter to the sage executable, so it is 
interpreted as a plain python file. I tried to import only the parts of Sage 
that I needed, but it turned into problems with circular dependencies. 

Then we import the MPI module, that we need for passing messages bewteen our 
processes, and set up a `comm` object that will handle that communication. It 
gives us the values of `rank` (a number that identifies the current process) 
and `size` (the total number of processes running).

### The master process

Now we go with a block of code that is under the case

```python
if rank ==0:
```

that is, it will only be run by the first process (it will act as a master 
process, sending the jobs to the others, and getting their answers). This 
process will start reading the input data and preprocessing it to put it in a 
suitable form:

```python
    f = open('Rolfsen.rdf')
    lines = f.readlines()
    f.close()

    def link_from_pd(st):
        l1 = [map(int,_.split(','))   for _  in st.replace(' ','').replace('</sub>','').replace('X','').split('<sub>')[1:] if  ',' in _]
        l1 = l1 + [map(int,list(_))   for _  in  st.replace(' ','').replace('</sub>','').replace('X','').split('<sub>')[1:] if not ',' in _]
        return l1

    knots = {}

    for l in lines:
        if 'PD_Pres' in l.split(' ')[1]:
            nombre = l.split(' ')[0]
            if not nombre == '<knot:0_1>':
                pd = l.split('"')[1]
                knots[nombre] = {'PD': link_from_pd(pd)}

    for l in lines:
        if 'HOMFLY' in l:
            nombre = l.split(' ')[0]
            if not nombre == '<knot:0_1>':
                hf = l.split('"')[1].replace('<math>','').replace('</math>','').replace('{','(').replace('}',')')
                knots[nombre]['homfly'] = hf

```
Don't panic if these lines look scary. It is enough to know that it is the 
part where we read the data file and prepare the information in a structure
that will be useful later. In more detail, these lines tell this master process
to read the file `Rolfsen.rdf` and extract from it the PD codes of the knots 
and their HOMFLY polynomial. The result is the dictionary `knots` whose keys 
are the names of the knots, and the data of each node is a text string containing
its HOMFLY polynomial and the PD code according to the knot atlas.

Then we prepare lists of nodes to send works to, and the works to send them:

```python
    freenodes = range(1, size)
    unfinishednodes = range(1,size)
    works = knots
    
```

Then we start by sending one work to each node:

```python 
    while freenodes: # send first job to each worker
        tr = works.popitem()
        nodetosend = freenodes.pop(0)
        comm.send((tr[0], tr[1]['PD'], tr[1]['homfly']), dest=nodetosend)
```

The important part here is the last line: it uses the function `comm.send`, 
that sends an object (in this case, a tuple with the name of the knot, its PD 
code and its homfly polynomial, that will be double checked by the process that 
receives it), to the process identified by the number passed as `dest`. The 
execution of the program will be paused here until the corresponding process 
receives the message (which in principle should be almost inmediate, since the 
other process will ask for this message at the beginning, as we will see later).

Once we have fed all the workers with a program to process, we will get into a 
loop where we get back the results that the workers send back, and feed them 
with new works to do if they are available. When we run out of knots to check, 
we will send a message to the workers telling them to finish:

```python
    results = []
    
    while unfinishednodes:
        answer = comm.recv()
        nodo = answer[1]
        print 'still {} works to run, {} already finished'.format(len(works), len(results))
        results.append(answer[0])
        if works:
            tr = works.popitem()
            comm.send((tr[0], tr[1]['PD'], tr[1]['homfly']), dest=nodo)
        else:
            comm.send('End',dest=nodo)
            unfinishednodes.remove(nodo)
```
note that the loop starts with the function `comm.recv()`, that means that this 
process will wait until some process sends it a message with the result of a 
computation. This message will consist on a tuple with the result of a 
computation and the number of the process that sent it. If there are still works 
available, a new work will be sent to the process. Otherwise, the string `End` 
will be sent to tell it that it must end, and the process will be removed from 
the list of works that have not finished.

Finally, when all the works are done, we print the result of the computation:

```python
    print "the polynomials don't match in the following cases"
    print [res for res in results if not res[-1]]    
    print "Finished"
```
In this case, if all went well it should print that there are no cases where 
the HOMFLY polynomial computed by sage and the one in the knot atlas differ. 
This messages will be printed to the putput file that we defined in the slurm 
script.

### The working processes

Here we will see the code that is run by the workers. It is the code block 
under the case:

```python
else:
```

We start setting up some objects that will be needed in the computation:

```python
    from sage.misc.parser import Parser

    R = LaurentPolynomialRing(ZZ,2, 'a,z')
    (a,z) = R.gens()
    parser = Parser(make_var={'z':z, 'a':a})
```
In particular a Laurent polynomial ring where our HOMFLY polynomials will live 
(note that it wasn't defined with the `R.<a,z> = LaurentPolynomialRing(ZZ)` 
syntax, since we are running a `py` file, and hence there is no sage preparsing 
going on). Then we define a parser that will convert the test strings into 
polynomials in this ring.

The next block is the main loop of the worker:

```python
    
    while True:
        link = comm.recv()
        if link == 'End':
            break
        
        K = Knot(link[1])
        f1 = parser.parse(link[2])
        f2 = K.mirror_image().homfly_polynomial('a','z', normalization='az')
        igual = bool(f1==f2)
        
        comm.send(([link[0], f1, f2, igual],rank), dest=0)
```
This loop will go on unti we receive an `End` message. In each iteration, we 
receive a message with a link (remember, it was a tuple with the name, the PD 
code and the homfly polynomial). We construct the knot from the PD code, 
compute the homfly polynomial (we have to take the mirror image because sage 
and the knot atlas use different convention for the PD codes); and compare it 
with the one in the knot atlas. We then send a message back to the master 
process, with the result of this computation, and the `rank` variable 
(remember, the master process needs to keep track of which process is 
available).

### Closing up

Finally we syncronize the communications between the processes and exit.

```python
comm.Barrier()

exit
```

I am not really sure if these two commands are really necessary, but it 
doesen't hurt to put them.
