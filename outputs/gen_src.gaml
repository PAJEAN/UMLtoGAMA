model lunerayFlu

global {
    int nb_people <- 2147;
    int nb_infected_init <- 5;
    float step <- 5 #mn;
    file roads_shapefile <- file("../includes/roads.shp");
    file buildings_shapefile <- file("../includes/buildings.shp");
    geometry shape <- envelope(roads_shapefile);
    graph road_network;
    int nb_people_infected <- nb_infected_init update: people count (each.is_infected);
    int nb_people_not_infected <- nb_people - nb_infected_init update: nb_people - nb_people_infected;
    float infected_rate update: nb_people_infected/nb_people;

    init {
        
        create people number: nb_people {
        }
        
        
        create building from: buildings_shapefile {
        }
        
        
        create road from: roads_shapefile {
        }
        
        road_network <- as_edge_graph(road); ask nb_infected_init among people { is_infected <- true; }
    }

    reflex end_simulation when: infected_rate = 1.0  {
        do pause;
    }
}

experiment main {
    output {
        display map {
            species road aspect:geom; species building aspect:geom; species people aspect:circle;
        }
    }
}

species people control: fsm skills: [moving] {
    float speed <- (2 + rnd(3)) #km/#h;
    bool is_infected <- false;
    point target;

    aspect circle {
        draw circle(10) color:is_infected ? #red : #green;
    }
    action stay {
        if flip(0.05) { target <- any_location_in (one_of(building)); }
    }
    action move {
        do goto target: target on: road_network; if (location = target) { target <- nil; }
    }
    action infect {
        ask people at_distance 10 #m { if flip(0.05) { is_infected <- true; } }
    }
    init {
        location <- any_location_in(one_of(building));
    }

    state EntryPoint initial: true {
        do stay();
        transition to: move when: target != nil;
    }
    state move {
        do move();
        transition to: EntryPoint when: target = nil;
        transition to: infected when: is_infected;
    }
    state infected {
        do infect();
        transition to: move when: target != nil;
        transition to: EntryPoint when: target = nil;
    }
}
        

species road {

    aspect geom {
        draw shape color: #black;
    }

}
        

species building {

    aspect geom {
        draw shape color: #gray;
    }

}
        
