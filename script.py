from sage.all import *

from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.size


if rank ==0:

    f = open('Rolfsen.rdf')
    lines = f.readlines()
    f.close()

    def link_from_pd(st):
        l1 = [map(int,_.split(','))   for _  in  st.replace(' ','').replace('</sub>','').replace('X','').split('<sub>')[1:] if  ',' in _]
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
                
    freenodes = range(1, size)
    unfinishednodes = range(1,size)
    works = knots
    
    while freenodes: # send first job to each worker
        tr = works.popitem()
        nodetosend = freenodes.pop(0)
        comm.send((tr[0], tr[1]['PD'], tr[1]['homfly']), dest=nodetosend)
    
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
    print "the polynomials don't match in the following cases"
    print [res for res in results if not res[-1]]    
    print "Finished"

else:

    from sage.misc.parser import Parser

    R = LaurentPolynomialRing(ZZ,2, 'a,z')
    (a,z) = R.gens()
    parser = Parser(make_var={'z':z, 'a':a})
    
    
    while True:
        link = comm.recv()
        if link == 'End':
            break
        
        K = Knot(link[1])
        f1 = parser.parse(link[2])
        f2 = K.mirror_image().homfly_polynomial('a','z', normalization='az')
        igual = bool(f1==f2)
        
        comm.send(([link[0], f1, f2, igual],rank), dest=0)

comm.Barrier()

exit
