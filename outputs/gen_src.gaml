model preyPredator

global {
    float prey_max_energy <- 1.0;
    float prey_max_transfert <- 0.1;
    float prey_energy_consum <- 0.05;
    float predator_max_energy <- 1.0;
    float predator_energy_transfert <- 0.5;
    float predator_energy_consum <- 0.02;
    float prey_proba_reproduce <- 0.01;
    int prey_nb_max_offsprings <- 5;
    float prey_energy_reproduce <- 0.5;
    float predator_proba_reproduce <- 0.01;
    int predator_nb_max_offsprings <- 3;
    float predator_energy_reproduce <- 0.5;

    init {
        
        create prey {
            color <- #blue;
            max_energy <- prey_max_energy;
            max_transfert <- prey_max_transfert;
            energy_consum <- prey_energy_consum;
            proba_reproduce <- prey_proba_reproduce;
            nb_max_offsprings <- prey_nb_max_offsprings;
            energy_reproduce <- prey_energy_reproduce;
            energy <- rnd(prey_max_energy);
        }
        
        
        create predator {
            color <- #red;
            max_energy <- predator_max_energy;
            energy_transfert <- predator_energy_transfert;
            energy_consum <- predator_energy_consum;
            proba_reproduce <- predator_proba_reproduce;
            nb_max_offsprings <- predator_nb_max_offsprings;
            energy_reproduce <- predator_energy_reproduce;
            energy <- rnd(predator_max_energy);
        }
        
    }

}

experiment prey_predator type: gui  {
    output {
        display main_display {
            grid vegetation_cell lines: #black; species prey aspect: base; species predator aspect: base;
        }
    }
}

species generic_species control: fsm {
    float size <- 1.0;
    rgb color;
    float max_energy;
    float proba_reproduce;
    int nb_max_offsprings;
    float energy update: energy - energy_consum max: max_energy;
    float energy_reproduce;
    float max_transfert;
    vegetation_cell my_cell <- one_of(vegetation_cell);
    float energy_consum;
    int continent <- 0;

    action basic_move {
        my_cell <- one_of(my_cell.neighbors2()); location <- my_cell.location;
    }
    action eat {
        energy <- energy + energy_from_eat();
    }
    action die {
        do die;
    }
    action reproduce {
        return;
    }
    float energy_from_eat {
        return 0.0;
    }
    aspect base {
        draw circle(size) color: color;
    }
    init {
        location <- my_cell.location;
    }

    state EntryPoint initial: true {
        do basic_move();
        do eat();
        transition to: Reproduce when: (energy >= energy_reproduce) and (flip(proba_reproduce));
        transition to: FinalPoint when: energy <= 0;
    }
    state Reproduce {
        do reproduce();
        transition to: EntryPoint when: (energy < energy_reproduce) or !(flip(proba_reproduce));
        transition to: FinalPoint when: energy <= 0;
    }
    state FinalPoint final: true {
        do die();
    }
}
        

species prey parent: generic_species {

    float energy_from_eat {
        float energy_transfert <- 0.0; if(my_cell.food > 0) { energy_transfert <- min([max_transfert, my_cell.food]); my_cell.food <- my_cell.food - energy_transfert; } return energy_transfert;
    }
    action reproduce {
        int nb_offsprings <- rnd(1, nb_max_offsprings); create species(self) number: nb_offsprings { color <- #blue; max_energy <- prey_max_energy; max_transfert <- prey_max_transfert; energy_consum <- prey_energy_consum; proba_reproduce <- prey_proba_reproduce; nb_max_offsprings <- prey_nb_max_offsprings; energy_reproduce <-  prey_energy_reproduce;  energy <- myself.energy / nb_offsprings; my_cell <- myself.my_cell; location <- my_cell.location; } energy <- energy / nb_offsprings;
    }

}
        

species predator parent: generic_species {
    float energy_transfert;

    float energy_from_eat {
        list<prey> reachable_preys <- prey inside (my_cell); if(! empty(reachable_preys)) { ask one_of (reachable_preys) { do die; } return energy_transfert; } return 0.0;
    }
    action reproduce {
        int nb_offsprings <- rnd(1, nb_max_offsprings); create species(self) number: nb_offsprings { color <- #red; max_energy <- predator_max_energy; energy_transfert <- predator_energy_transfert; energy_consum <- predator_energy_consum; proba_reproduce <- predator_proba_reproduce; nb_max_offsprings <- predator_nb_max_offsprings; energy_reproduce <- predator_energy_reproduce; energy <- myself.energy / nb_offsprings; my_cell <- myself.my_cell; location <- my_cell.location; } energy <- energy / nb_offsprings;
    }

}
        

grid vegetation_cell width: 50 height: 50 neighbors: 4 {
    float max_food <- 1.0;
    float food_prod <- rnd(0.01);
    float food <- rnd(1.0) max: max_food update: food + food_prod;
    rgb color <- rgb(int(255 * (1 - food)), 255, int(255 * (1 - food))) update: rgb(int(255 * (1 - food)), 255, int(255 * (1 - food)));

    list<vegetation_cell> neighbors2 {
        return (self neighbors_at 2);
    }

}
        
